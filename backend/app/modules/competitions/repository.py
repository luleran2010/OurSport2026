"""Competitions persistence. Player reads always go through `visibility_filter`."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, exists, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.competitions.models import (
    Consent,
    Group,
    LotsDraw,
    Match,
    Organisation,
    Pitch,
    Player,
    ProcessingAgreement,
    Sport,
    Team,
    Tournament,
    TournamentStaff,
    TournamentTeam,
)

MANAGING_ROLES = ("owner", "organiser")


@dataclass(frozen=True)
class Audience:
    """What a viewer may see of players: built per request by the service."""

    family_player_ids: frozenset[UUID] = field(default_factory=frozenset)
    staff_tournament_ids: frozenset[UUID] = field(default_factory=frozenset)


def visibility_filter(audience: Audience) -> ColumnElement[bool]:
    """Players a viewer may see: public ones, their own family's `family_only` players,
    and every player of a team in a tournament they manage."""
    clauses: list[ColumnElement[bool]] = [Player.visibility == "public"]
    if audience.family_player_ids:
        clauses.append(
            and_(
                Player.visibility == "family_only",
                Player.id.in_(audience.family_player_ids),
            )
        )
    if audience.staff_tournament_ids:
        clauses.append(
            exists().where(
                TournamentTeam.team_id == Player.team_id,
                TournamentTeam.tournament_id.in_(audience.staff_tournament_ids),
            )
        )
    return or_(*clauses) if clauses else false()


async def slug_taken(session: AsyncSession, model: Any, slug: str) -> bool:
    result = await session.execute(select(exists().where(model.slug == slug)))
    return bool(result.scalar())


async def managed_tournament_ids(session: AsyncSession, user_id: UUID | None) -> frozenset[UUID]:
    if user_id is None:
        return frozenset()
    result = await session.execute(
        select(TournamentStaff.tournament_id).where(
            TournamentStaff.user_id == user_id, TournamentStaff.role.in_(MANAGING_ROLES)
        )
    )
    return frozenset(result.scalars())


async def team_in_tournaments(
    session: AsyncSession, team_id: UUID, tournament_ids: Iterable[UUID]
) -> bool:
    ids = list(tournament_ids)
    if not ids:
        return False
    result = await session.execute(
        select(
            exists().where(TournamentTeam.team_id == team_id, TournamentTeam.tournament_id.in_(ids))
        )
    )
    return bool(result.scalar())


async def visible_players(session: AsyncSession, team_id: UUID, audience: Audience) -> list[Player]:
    result = await session.execute(
        select(Player)
        .where(Player.team_id == team_id, visibility_filter(audience))
        .order_by(Player.shirt_number.nulls_last(), Player.display_name)
    )
    return list(result.scalars())


async def visible_player(
    session: AsyncSession, player_id: UUID, audience: Audience
) -> Player | None:
    result = await session.execute(
        select(Player).where(Player.id == player_id, visibility_filter(audience))
    )
    return result.scalar_one_or_none()


async def player_for_update(session: AsyncSession, player_id: UUID) -> Player | None:
    """Unfiltered, for writes by staff only; the service checks the caller first."""
    result = await session.execute(select(Player).where(Player.id == player_id).with_for_update())
    return result.scalar_one_or_none()


async def active_consent_scopes(session: AsyncSession, player_id: UUID) -> frozenset[str]:
    result = await session.execute(
        select(Consent.scope).where(Consent.player_id == player_id, Consent.withdrawn_at.is_(None))
    )
    return frozenset(result.scalars())


async def consent_for_update(session: AsyncSession, consent_id: UUID) -> Consent | None:
    result = await session.execute(
        select(Consent).where(Consent.id == consent_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def counts(session: AsyncSession, tournament_id: UUID) -> dict[str, int]:
    async def count(model: Any) -> int:
        result = await session.execute(
            select(func.count()).select_from(model).where(model.tournament_id == tournament_id)
        )
        return int(result.scalar_one())

    return {
        "teams": await count(TournamentTeam),
        "groups": await count(Group),
        "matches": await count(Match),
    }


async def matches_of(session: AsyncSession, tournament_id: UUID) -> list[Match]:
    result = await session.execute(
        select(Match)
        .where(Match.tournament_id == tournament_id)
        .order_by(Match.starts_at, Match.code)
    )
    return list(result.scalars())


async def delete_tournament(session: AsyncSession, tournament_id: UUID) -> None:
    """Delete a tournament; the database cascades to every row that belongs to it."""
    await session.execute(delete(Tournament).where(Tournament.id == tournament_id))


async def tournament_by_slug(session: AsyncSession, slug: str) -> Tournament | None:
    result = await session.execute(select(Tournament).where(Tournament.slug == slug))
    return result.scalar_one_or_none()


async def organisation_id_by_slug(session: AsyncSession, slug: str) -> UUID | None:
    result = await session.execute(select(Organisation.id).where(Organisation.slug == slug))
    return result.scalar_one_or_none()


async def match_for_update(session: AsyncSession, match_id: UUID) -> Match | None:
    result = await session.execute(select(Match).where(Match.id == match_id).with_for_update())
    return result.scalar_one_or_none()


async def bump_last_seq(session: AsyncSession, match_id: UUID) -> int:
    result = await session.execute(
        update(Match)
        .where(Match.id == match_id)
        .values(last_seq=Match.last_seq + 1)
        .returning(Match.last_seq)
    )
    return int(result.scalar_one())


async def groups_of(session: AsyncSession, tournament_id: UUID) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.tournament_id == tournament_id).order_by(Group.order)
    )
    return list(result.scalars())


async def entries_of(
    session: AsyncSession, tournament_id: UUID
) -> list[tuple[TournamentTeam, Team]]:
    result = await session.execute(
        select(TournamentTeam, Team)
        .join(Team, Team.id == TournamentTeam.team_id)
        .where(TournamentTeam.tournament_id == tournament_id)
        .order_by(TournamentTeam.seed.nulls_last(), Team.name)
    )
    return [(entry, team) for entry, team in result]


async def pitches_of(session: AsyncSession, tournament_id: UUID) -> list[Pitch]:
    venue_ids = select(Match.venue_id).where(Match.tournament_id == tournament_id).distinct()
    result = await session.execute(
        select(Pitch).where(Pitch.venue_id.in_(venue_ids)).order_by(Pitch.order)
    )
    return list(result.scalars())


async def public_tournaments(
    session: AsyncSession,
    organisation_id: UUID | None,
    series_id: UUID | None,
    team_id: UUID | None,
) -> list[Tournament]:
    query = select(Tournament).where(Tournament.status != "draft")
    if organisation_id is not None:
        query = query.where(Tournament.organisation_id == organisation_id)
    if series_id is not None:
        query = query.where(Tournament.series_id == series_id)
    if team_id is not None:
        query = query.where(
            Tournament.id.in_(
                select(TournamentTeam.tournament_id).where(TournamentTeam.team_id == team_id)
            )
        )
    result = await session.execute(query.order_by(Tournament.starts_on.desc().nulls_last()))
    return list(result.scalars())


async def team_matches(session: AsyncSession, team_id: UUID) -> list[Match]:
    published = select(Tournament.id).where(Tournament.status != "draft")
    result = await session.execute(
        select(Match)
        .where(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            Match.tournament_id.in_(published),
        )
        .order_by(Match.starts_at)
    )
    return list(result.scalars())


async def tournaments_in(session: AsyncSession, statuses: tuple[str, ...]) -> list[Tournament]:
    result = await session.execute(select(Tournament).where(Tournament.status.in_(statuses)))
    return list(result.scalars())


async def open_match_count(session: AsyncSession, tournament_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Match)
        .where(
            Match.tournament_id == tournament_id,
            Match.status.in_(("scheduled", "live", "postponed")),
        )
    )
    return int(result.scalar_one())


async def matches_starting(session: AsyncSession, start: Any, end: Any) -> list[Match]:
    published = select(Tournament.id).where(Tournament.status.in_(("upcoming", "active")))
    result = await session.execute(
        select(Match)
        .where(
            Match.status == "scheduled",
            Match.starts_at >= start,
            Match.starts_at < end,
            Match.tournament_id.in_(published),
        )
        .order_by(Match.starts_at)
    )
    return list(result.scalars())


async def consents_of(session: AsyncSession, player_id: UUID) -> list[Consent]:
    result = await session.scalars(select(Consent).where(Consent.player_id == player_id))
    return list(result)


async def delete_consents(session: AsyncSession, player_id: UUID) -> None:
    await session.execute(delete(Consent).where(Consent.player_id == player_id))


async def has_agreement(session: AsyncSession, organisation_id: UUID, version: str) -> bool:
    found = await session.scalar(
        select(ProcessingAgreement.id).where(
            ProcessingAgreement.organisation_id == organisation_id,
            ProcessingAgreement.version == version,
        )
    )
    return found is not None


async def runs_organisation(session: AsyncSession, user_id: UUID, organisation_id: UUID) -> bool:
    """Accepted its terms before, or runs one of its tournaments."""
    accepted = await session.scalar(
        select(ProcessingAgreement.id).where(
            ProcessingAgreement.organisation_id == organisation_id,
            ProcessingAgreement.accepted_by == user_id,
        )
    )
    if accepted is not None:
        return True
    staff = await session.scalar(
        select(TournamentStaff.tournament_id)
        .join(Tournament, Tournament.id == TournamentStaff.tournament_id)
        .where(TournamentStaff.user_id == user_id, Tournament.organisation_id == organisation_id)
    )
    return staff is not None


async def lots_of(session: AsyncSession, tournament_id: UUID) -> dict[UUID | None, list[str]]:
    rows = await session.scalars(
        select(LotsDraw)
        .where(LotsDraw.tournament_id == tournament_id)
        .order_by(LotsDraw.created_at, LotsDraw.id)
    )
    return {r.group_id: list(r.order) for r in rows}  # later draws replace earlier ones


async def search(
    session: AsyncSession,
    q: str,
    kinds: set[str],
    sport: str | None,
    region: str | None,
    limit: int,
) -> dict[str, list[Any]]:
    """Organisations, published tournaments, teams of published tournaments and public
    players whose names contain `q` (players: the visibility filter for anyone)."""
    like = f"%{q}%"
    out: dict[str, list[Any]] = {}
    published = select(Tournament.id).where(Tournament.status != "draft")
    if "organisation" in kinds:
        orgs = select(Organisation).where(Organisation.name.ilike(like))
        if region:
            orgs = orgs.where(Organisation.town.ilike(f"%{region}%"))
        if sport:
            orgs = orgs.where(Organisation.sports.contains([sport]))
        out["organisation"] = list(await session.scalars(orgs.limit(limit)))
    if "tournament" in kinds:
        tournaments = select(Tournament).where(
            Tournament.status != "draft", Tournament.name.ilike(like)
        )
        if sport:
            tournaments = tournaments.where(Tournament.sport == sport)
        out["tournament"] = list(await session.scalars(tournaments.limit(limit)))
    entered = select(TournamentTeam.team_id).where(TournamentTeam.tournament_id.in_(published))
    if "team" in kinds:
        teams = select(Team).where(Team.name.ilike(like), Team.id.in_(entered))
        out["team"] = list(await session.scalars(teams.limit(limit)))
    if "player" in kinds:
        players = (
            select(Player, Team.name)
            .join(Team, Team.id == Player.team_id)
            .where(
                Player.display_name.ilike(like),
                visibility_filter(Audience()),
                Player.team_id.in_(entered),
            )
        )
        out["player"] = list((await session.execute(players.limit(limit))).all())
    return out


async def staff_of(session: AsyncSession, tournament_id: UUID) -> list[TournamentStaff]:
    result = await session.scalars(
        select(TournamentStaff).where(TournamentStaff.tournament_id == tournament_id)
    )
    return list(result)


async def published_in_region(
    session: AsyncSession, region: str | None, limit: int
) -> list[Tournament]:
    """Published tournaments, newest first; with `region`, of organisations in that town."""
    query = select(Tournament).where(Tournament.status != "draft")
    if region:
        towns = select(Organisation.id).where(Organisation.town.ilike(f"%{region}%"))
        query = query.where(Tournament.organisation_id.in_(towns))
    result = await session.scalars(
        query.order_by(Tournament.starts_on.desc().nulls_last()).limit(limit)
    )
    return list(result)


async def organisation_teams(session: AsyncSession, organisation_id: UUID) -> list[Team]:
    result = await session.scalars(
        select(Team).where(Team.organisation_id == organisation_id).order_by(Team.name)
    )
    return list(result)


# --- catalogue lists (T-066): keyset pages ordered by name (or newest first) ----------------


def _after_name(model: Any, after: tuple[str, UUID] | None) -> ColumnElement[bool] | None:
    if after is None:
        return None
    name, last_id = after
    return or_(model.name > name, and_(model.name == name, model.id > last_id))


async def sports(session: AsyncSession) -> list[Sport]:
    return list(await session.scalars(select(Sport).order_by(Sport.code)))


async def organisations_page(
    session: AsyncSession, after: tuple[str, UUID] | None, limit: int, sport: str | None
) -> list[Organisation]:
    query = select(Organisation)
    if (clause := _after_name(Organisation, after)) is not None:
        query = query.where(clause)
    if sport:
        query = query.where(Organisation.sports.contains([sport]))
    result = await session.scalars(query.order_by(Organisation.name, Organisation.id).limit(limit))
    return list(result)


EPOCH = date(1900, 1, 1)


async def published_page(
    session: AsyncSession,
    after: tuple[date, UUID] | None,
    limit: int,
    organisation_id: UUID | None,
    sport: str | None,
    status: str | None,
) -> list[Tournament]:
    """Published tournaments, newest start first (then by id)."""
    starts = func.coalesce(Tournament.starts_on, EPOCH)
    query = select(Tournament).where(Tournament.status != "draft")
    if after is not None:
        query = query.where(
            or_(starts < after[0], and_(starts == after[0], Tournament.id > after[1]))
        )
    if organisation_id is not None:
        query = query.where(Tournament.organisation_id == organisation_id)
    if sport:
        query = query.where(Tournament.sport == sport)
    if status:
        query = query.where(Tournament.status == status)
    result = await session.scalars(query.order_by(starts.desc(), Tournament.id).limit(limit))
    return list(result)


async def team_counts(session: AsyncSession, tournament_ids: list[UUID]) -> dict[UUID, int]:
    rows = await session.execute(
        select(TournamentTeam.tournament_id, func.count())
        .where(TournamentTeam.tournament_id.in_(tournament_ids))
        .group_by(TournamentTeam.tournament_id)
    )
    return {tid: n for tid, n in rows.tuples()}


async def organisation_names(session: AsyncSession, ids: Iterable[UUID]) -> dict[UUID, str]:
    rows = await session.execute(
        select(Organisation.id, Organisation.name).where(Organisation.id.in_(list(ids)))
    )
    return {oid: name for oid, name in rows.tuples()}


async def published_teams_page(
    session: AsyncSession,
    after: tuple[str, UUID] | None,
    limit: int,
    tournament_id: UUID | None,
    organisation_id: UUID | None,
) -> list[Team]:
    """Teams entered in a published tournament (no contact details leave the service)."""
    published = select(Tournament.id).where(Tournament.status != "draft")
    if tournament_id is not None:
        published = published.where(Tournament.id == tournament_id)
    entered = select(TournamentTeam.team_id).where(TournamentTeam.tournament_id.in_(published))
    query = select(Team).where(Team.id.in_(entered))
    if organisation_id is not None:
        query = query.where(Team.organisation_id == organisation_id)
    if (clause := _after_name(Team, after)) is not None:
        query = query.where(clause)
    result = await session.scalars(query.order_by(Team.name, Team.id).limit(limit))
    return list(result)


async def published_entries_of_teams(
    session: AsyncSession, team_ids: list[UUID]
) -> list[tuple[UUID, Tournament]]:
    """(team id, tournament) for every published tournament these teams are entered in."""
    rows = await session.execute(
        select(TournamentTeam.team_id, Tournament)
        .join(Tournament, Tournament.id == TournamentTeam.tournament_id)
        .where(TournamentTeam.team_id.in_(team_ids), Tournament.status != "draft")
        .order_by(func.coalesce(Tournament.starts_on, EPOCH).desc())
    )
    return [(team_id, t) for team_id, t in rows.tuples()]


async def staff_roles_of(session: AsyncSession, user_id: UUID) -> list[tuple[str, Tournament]]:
    rows = await session.execute(
        select(TournamentStaff.role, Tournament)
        .join(Tournament, Tournament.id == TournamentStaff.tournament_id)
        .where(TournamentStaff.user_id == user_id)
        .order_by(Tournament.name)
    )
    return [(role, t) for role, t in rows.tuples()]


async def agreed_organisations(session: AsyncSession, user_id: UUID) -> list[UUID]:
    rows = await session.scalars(
        select(ProcessingAgreement.organisation_id)
        .where(ProcessingAgreement.accepted_by == user_id)
        .distinct()
    )
    return list(rows)
