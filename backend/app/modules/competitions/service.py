"""Competitions: organisations, tournaments, teams, players and their visibility.

Junior protection (docs/09-security-privacy.md): players under 18 (by birth year, or in a
junior team when the year is unknown) start `hidden`; `family_only` needs a `profile`
consent and `public` needs `profile` + `stats`. Withdrawing a consent lowers the
visibility at once. U12 and younger tournaments hide probabilities by default.
"""

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, jobs
from app.core.db import transaction
from app.core.errors import Conflict, NotFound, ProcessingAgreementRequired, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import CursorValue, Page, PageParams, decode_cursor, encode_cursor
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.accounts import service as accounts
from app.modules.accounts.schemas import Membership, MeParts, StaffTournament
from app.modules.competitions import repository
from app.modules.competitions.models import (
    Consent,
    Group,
    LotsDraw,
    Match,
    Organisation,
    Pitch,
    Player,
    ProcessingAgreement,
    Team,
    TeamAlias,
    Tournament,
    TournamentSeries,
    TournamentStaff,
    TournamentTeam,
    Venue,
)
from app.modules.competitions.schemas import (
    AgreementOut,
    ConsentCreate,
    ConsentOut,
    EntryOut,
    FilmingPlayer,
    GroupOut,
    MatchOut,
    OrganisationColors,
    OrganisationCreate,
    OrganisationOut,
    OrganisationPage,
    OrganisationSummary,
    ParticipantConsent,
    ParticipantData,
    ParticipantPlayer,
    ParticipantTeam,
    PitchOut,
    PlayerCreate,
    PlayerOut,
    RosterPlayer,
    ScheduleUpdate,
    SearchHit,
    SearchResult,
    SeriesPage,
    SettingsPatch,
    SportOut,
    StaffIn,
    StaffOut,
    StaffRole,
    TeamContacts,
    TeamCreate,
    TeamDetail,
    TeamListItem,
    TeamOut,
    TournamentCreate,
    TournamentListItem,
    TournamentOut,
    TournamentSettings,
    TournamentStructure,
    Visibility,
)

PROCESSING_TERMS_VERSION = "2026-10"
ADULT_AGE = 18
NO_PROBABILITIES = frozenset({"u12", "u11", "u10", "u9"})
_REQUIRED_CONSENTS: dict[str, frozenset[str]] = {
    "hidden": frozenset(),
    "family_only": frozenset({"profile"}),
    "public": frozenset({"profile", "stats"}),
}
_OPENNESS = ("hidden", "family_only", "public")  # least to most visible


# --- names -----------------------------------------------------------------------------------


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "x"


def normalise_alias(name: str) -> str:
    """A team name for matching across editions: case, accents and punctuation ignored."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    letters = re.sub("[.'\u2019]", "", letters)  # "F.C." = "FC", "St. John's" = "St Johns"
    return " ".join(re.sub(r"[^\w]+", " ", letters).split())


async def _unique_slug(db: AsyncSession, model: Any, name: str) -> str:
    base = slugify(name)
    slug, n = base, 1
    while await repository.slug_taken(db, model, slug):
        n += 1
        slug = f"{base}-{n}"
    return slug


# --- organisations and tournaments -----------------------------------------------------------


async def create_organisation(
    db: AsyncSession, clock: Clock, viewer: Viewer, data: OrganisationCreate
) -> OrganisationOut:
    """Create an organisation; its creator accepts the data processing terms."""
    assert viewer.user_id is not None
    now = clock.now()
    async with transaction(db):
        organisation = Organisation(
            id=new_id(),
            kind=data.kind,
            name=data.name,
            slug=await _unique_slug(db, Organisation, data.name),
            town=data.town,
            sports=list(data.sports),
            created_at=now,
        )
        db.add(organisation)
        db.add(
            ProcessingAgreement(
                id=new_id(),
                organisation_id=organisation.id,
                version=PROCESSING_TERMS_VERSION,
                accepted_by=viewer.user_id,
                accepted_at=now,
            )
        )
        await db.flush()
        await events.publish(db, events.OrganisationCreated(organisation.id, viewer.user_id))
    return OrganisationOut(
        id=organisation.id,
        kind=organisation.kind,
        name=organisation.name,
        slug=organisation.slug,
        town=organisation.town,
        sports=organisation.sports,
    )


def default_settings(age_group: str) -> TournamentSettings:
    junior = age_group != "adult"
    return TournamentSettings(
        show_probabilities=age_group not in NO_PROBABILITIES,
        filming_policy="consent_required" if junior else "notice",
    )


async def create_tournament(
    db: AsyncSession, clock: Clock, owner_user_id: UUID, data: TournamentCreate
) -> TournamentOut:
    """A draft tournament with age-appropriate settings; the creator is its owner."""
    now = clock.now()
    settings = data.settings or default_settings(data.age_group)
    async with transaction(db):
        tournament = Tournament(
            id=new_id(),
            series_id=data.series_id,
            edition_label=data.edition_label,
            name=data.name,
            slug=await _unique_slug(db, Tournament, data.name),
            sport=data.sport,
            organisation_id=data.organisation_id,
            status="draft",
            starts_on=data.starts_on,
            ends_on=data.ends_on,
            time_zone=data.time_zone,
            age_group=data.age_group,
            is_junior=data.age_group != "adult",
            settings=settings.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        db.add(tournament)
        db.add(TournamentStaff(tournament_id=tournament.id, user_id=owner_user_id, role="owner"))
    return _tournament_out(tournament)


def _tournament_out(tournament: Tournament) -> TournamentOut:
    return TournamentOut(
        id=tournament.id,
        organisation_id=tournament.organisation_id,
        name=tournament.name,
        slug=tournament.slug,
        sport=tournament.sport,
        status=tournament.status,
        age_group=tournament.age_group,
        is_junior=tournament.is_junior,
        time_zone=tournament.time_zone,
        starts_on=tournament.starts_on,
        ends_on=tournament.ends_on,
        settings=TournamentSettings.model_validate(tournament.settings),
    )


async def add_staff(db: AsyncSession, tournament_id: UUID, user_id: UUID, role: StaffRole) -> None:
    async with transaction(db):
        await db.merge(TournamentStaff(tournament_id=tournament_id, user_id=user_id, role=role))


async def delete_draft_tournament(db: AsyncSession, tournament_id: UUID) -> None:
    """Remove a tournament that was never published, with everything that belongs to it
    (setup, uploads, drafts, rules: the foreign keys cascade). 409 once it is public."""
    async with transaction(db):
        tournament = await db.get(Tournament, tournament_id)
        if tournament is None:
            raise NotFound()
        if tournament.status != "draft":
            raise Conflict("a published tournament cannot be removed")
        await repository.delete_tournament(db, tournament_id)
    db.expunge_all()  # rows the cascade removed must not linger in the session


async def manages(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> bool:
    """Whether the viewer is an owner or organiser of the tournament."""
    return tournament_id in await repository.managed_tournament_ids(db, viewer.user_id)


# --- teams -----------------------------------------------------------------------------------


async def create_team(db: AsyncSession, clock: Clock, data: TeamCreate) -> TeamOut:
    """A team, findable later by its normalised name."""
    now = clock.now()
    async with transaction(db):
        team = Team(id=new_id(), created_at=now, **data.model_dump())
        db.add(team)
        db.add(
            TeamAlias(
                alias_normalised=normalise_alias(data.name),
                team_id=team.id,
                source="setup",
                created_at=now,
            )
        )
    return _team_out(team)


def _team_out(team: Team) -> TeamDetail:
    return TeamDetail(
        id=team.id,
        name=team.name,
        short_name=team.short_name,
        age_group=team.age_group,
        organisation_id=team.organisation_id,
    )


async def enter_team(
    db: AsyncSession, tournament_id: UUID, team_id: UUID, group_id: UUID | None = None
) -> None:
    async with transaction(db):
        db.add(TournamentTeam(tournament_id=tournament_id, team_id=team_id, group_id=group_id))


async def get_team(db: AsyncSession, viewer: Viewer, team_id: UUID) -> TeamDetail:
    """A team; contact details only for staff of a tournament the team plays in."""
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFound()
    detail = _team_out(team)
    managed = await repository.managed_tournament_ids(db, viewer.user_id)
    if await repository.team_in_tournaments(db, team_id, managed):
        detail.contacts = TeamContacts(
            contact_name=team.contact_name,
            contact_email=team.contact_email,
            contact_phone=team.contact_phone,
        )
    return detail


# --- players ---------------------------------------------------------------------------------


def _is_junior(birth_year: int | None, team_age_group: str, now: datetime) -> bool:
    if birth_year is not None:
        return now.year - birth_year < ADULT_AGE
    return team_age_group != "adult"


def _check_consents(visibility: str, consents: frozenset[str]) -> None:
    missing = _REQUIRED_CONSENTS[visibility] - consents
    if missing:
        raise ValidationFailed(
            f"a junior player can be '{visibility}' only with consent for "
            f"{', '.join(sorted(missing))}"
        )


def _player_out(player: Player) -> PlayerOut:
    return PlayerOut(
        id=player.id,
        team_id=player.team_id,
        display_name=player.display_name,
        shirt_number=player.shirt_number,
        visibility=player.visibility,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
    )


async def create_player(
    db: AsyncSession, clock: Clock, team_id: UUID, data: PlayerCreate
) -> PlayerOut:
    """A player; juniors start hidden and cannot be shown without guardian consent."""
    now = clock.now()
    async with transaction(db):
        team = await db.get(Team, team_id)
        if team is None:
            raise NotFound()
        junior = _is_junior(data.birth_year, team.age_group, now)
        visibility = data.visibility or ("hidden" if junior else "public")
        if junior:
            _check_consents(visibility, frozenset())
        player = Player(
            id=new_id(),
            team_id=team_id,
            display_name=data.display_name,
            shirt_number=data.shirt_number,
            birth_year=data.birth_year,
            visibility=visibility,
            created_at=now,
        )
        db.add(player)
    return _player_out(player)


async def set_player_visibility(
    db: AsyncSession, clock: Clock, player_id: UUID, visibility: Visibility
) -> PlayerOut:
    """Change who sees a player; a junior needs the matching consents."""
    async with transaction(db):
        player = await repository.player_for_update(db, player_id)
        if player is None:
            raise NotFound()
        team = await db.get(Team, player.team_id)
        assert team is not None
        if _is_junior(player.birth_year, team.age_group, clock.now()):
            _check_consents(visibility, await repository.active_consent_scopes(db, player.id))
        player.visibility = visibility
    return _player_out(player)


async def record_consent(
    db: AsyncSession, clock: Clock, player_id: UUID, data: ConsentCreate
) -> UUID:
    """Record a guardian's consent for one scope."""
    async with transaction(db):
        if await repository.player_for_update(db, player_id) is None:
            raise NotFound()
        consent = Consent(
            id=new_id(), player_id=player_id, granted_at=clock.now(), **data.model_dump()
        )
        db.add(consent)
    return consent.id


async def withdraw_consent(db: AsyncSession, clock: Clock, consent_id: UUID) -> PlayerOut:
    """Withdraw a consent; the player's visibility drops to what the rest still allows."""
    async with transaction(db):
        consent = await repository.consent_for_update(db, consent_id)
        if consent is None:
            raise NotFound()
        consent.withdrawn_at = clock.now()
        await db.flush()
        player = await repository.player_for_update(db, consent.player_id)
        assert player is not None
        team = await db.get(Team, player.team_id)
        assert team is not None
        if _is_junior(player.birth_year, team.age_group, clock.now()):
            scopes = await repository.active_consent_scopes(db, player.id)
            allowed = max(
                (v for v in _OPENNESS if _REQUIRED_CONSENTS[v] <= scopes), key=_OPENNESS.index
            )
            if _OPENNESS.index(player.visibility) > _OPENNESS.index(allowed):
                player.visibility = allowed
    return _player_out(player)


async def audience_of(db: AsyncSession, viewer: Viewer) -> repository.Audience:
    """What the viewer may see of players (family links and managed tournaments)."""
    return repository.Audience(
        family_player_ids=await accounts.family_player_ids(db, viewer.user_id),
        staff_tournament_ids=await repository.managed_tournament_ids(db, viewer.user_id),
    )


async def list_players(db: AsyncSession, viewer: Viewer, team_id: UUID) -> list[PlayerOut]:
    """A team's players that this viewer may see."""
    audience = await audience_of(db, viewer)
    return [_player_out(p) for p in await repository.visible_players(db, team_id, audience)]


async def get_player(db: AsyncSession, viewer: Viewer, player_id: UUID) -> PlayerOut:
    """One player, or 404 when the viewer may not see them (never 403: docs/09)."""
    player = await repository.visible_player(db, player_id, await audience_of(db, viewer))
    if player is None:
        raise NotFound()
    return _player_out(player)


async def get_tournament(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> TournamentOut:
    """A tournament; drafts exist only for their owners and organisers (404 otherwise)."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None or (
        tournament.status == "draft" and not await manages(db, viewer, tournament_id)
    ):
        raise NotFound()
    return _tournament_out(tournament)


async def set_rule_config(db: AsyncSession, tournament_id: UUID, rule_config_id: UUID) -> None:
    """Point the tournament at its confirmed rules (call inside the caller's transaction)."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None:
        raise NotFound()
    tournament.rule_config_id = rule_config_id


async def set_status(db: AsyncSession, tournament_id: UUID, status: str) -> None:
    """Move a tournament through its lifecycle (call inside the caller's transaction)."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None:
        raise NotFound()
    tournament.status = status


async def create_structure(
    db: AsyncSession, clock: Clock, tournament_id: UUID, structure: TournamentStructure
) -> dict[str, UUID]:
    """Write a published tournament's teams, groups, venue, pitches and matches.

    Runs inside the caller's (publish) transaction; returns the team id for each draft key.
    """
    now = clock.now()
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None:
        raise NotFound()
    async with transaction(db):
        groups = {}
        for order, name in enumerate(structure.groups):
            group = Group(id=new_id(), tournament_id=tournament_id, name=name, order=order)
            db.add(group)
            groups[name] = group.id
        venue = Venue(id=new_id(), name=structure.venue_name)
        db.add(venue)
        await db.flush()  # no ORM relationships: parents are written before their children
        pitches = {}
        for order, name in enumerate(structure.pitches):
            pitch = Pitch(
                id=new_id(), venue_id=venue.id, name=name, order=order, is_main=order == 0
            )
            db.add(pitch)
            pitches[name] = pitch.id
        team_ids: dict[str, UUID] = {}
        for entry in structure.teams:
            team = Team(
                id=new_id(),
                name=entry.name,
                short_name=entry.short_name,
                age_group=tournament.age_group,
                created_at=now,
            )
            db.add(team)
            db.add(
                TeamAlias(
                    alias_normalised=normalise_alias(entry.name),
                    team_id=team.id,
                    source="setup",
                    created_at=now,
                )
            )
            team_ids[entry.key] = team.id
        await db.flush()
        for entry in structure.teams:
            db.add(
                TournamentTeam(
                    tournament_id=tournament_id,
                    team_id=team_ids[entry.key],
                    group_id=groups.get(entry.group) if entry.group else None,
                    seed=entry.seed,
                    pot=entry.pot,
                    seeding_reason=entry.seeding_reason,
                )
            )
        for m in structure.matches:
            db.add(
                Match(
                    id=new_id(),
                    tournament_id=tournament_id,
                    group_id=groups.get(m.group) if m.group else None,
                    stage=m.stage,
                    code=m.code,
                    round=m.round,
                    home_team_id=team_ids.get(m.home_key) if m.home_key else None,
                    away_team_id=team_ids.get(m.away_key) if m.away_key else None,
                    home_source=m.home_source,
                    away_source=m.away_source,
                    venue_id=venue.id,
                    pitch_id=pitches[m.pitch],
                    starts_at=m.starts_at,
                    schedule_version=1,
                    status="scheduled",
                    data_level="events",
                    last_seq=0,
                )
            )
        tournament.status = "upcoming"
        tournament.format_spec = structure.format_spec
        tournament.policy_catalogue_version = structure.policy_catalogue_version
        tournament.updated_at = now
        await db.flush()
        await events.publish(db, events.TournamentPublished(tournament_id, tuple(pitches.values())))
    return team_ids


async def tournament_counts(db: AsyncSession, tournament_id: UUID) -> dict[str, int]:
    """Teams, groups and matches of a tournament (for checks and summaries)."""
    return await repository.counts(db, tournament_id)


def _match_out(m: Match) -> MatchOut:
    return MatchOut(
        id=m.id,
        tournament_id=m.tournament_id,
        code=m.code,
        stage=m.stage,
        group_id=m.group_id,
        home_team_id=m.home_team_id,
        away_team_id=m.away_team_id,
        home_source=m.home_source,
        away_source=m.away_source,
        pitch_id=m.pitch_id,
        starts_at=m.starts_at,
        status=m.status,
        result=m.result,
        data_level=m.data_level,
        last_seq=m.last_seq,
    )


async def list_matches(db: AsyncSession, tournament_id: UUID) -> list[MatchOut]:
    """A tournament's matches in kick-off order."""
    return [_match_out(m) for m in await repository.matches_of(db, tournament_id)]


async def find_tournament(db: AsyncSession, slug: str) -> TournamentOut | None:
    """A tournament by its slug (seed scripts, share links)."""
    tournament = await repository.tournament_by_slug(db, slug)
    return _tournament_out(tournament) if tournament else None


async def record_result(
    db: AsyncSession,
    match_id: UUID,
    result: dict[str, object],
    *,
    status: str = "finished",
    data_level: str | None = None,
) -> None:
    """Store a finished match's result (scoring calls this when a match ends)."""
    async with transaction(db):
        match = await db.get(Match, match_id)
        if match is None:
            raise NotFound()
        match.result = result
        match.status = status
        if data_level is not None:
            match.data_level = data_level


async def get_match(db: AsyncSession, match_id: UUID) -> MatchOut:
    match = await db.get(Match, match_id)
    if match is None:
        raise NotFound()
    return _match_out(match)


async def lock_match(db: AsyncSession, match_id: UUID) -> MatchOut:
    """The match row locked for this transaction (event ingestion is serialised per match)."""
    match = await repository.match_for_update(db, match_id)
    if match is None:
        raise NotFound()
    return _match_out(match)


async def next_event_seq(db: AsyncSession, match_id: UUID) -> int:
    """Assign the next event sequence number (inside the caller's transaction)."""
    return await repository.bump_last_seq(db, match_id)


async def set_match_status(db: AsyncSession, match_id: UUID, status: str) -> None:
    async with transaction(db):
        match = await db.get(Match, match_id)
        if match is None:
            raise NotFound()
        match.status = status


async def tournament_window(db: AsyncSession, tournament_id: UUID) -> TournamentOut:
    """A tournament's dates and time zone, whatever its status (for scorer passes)."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None:
        raise NotFound()
    return _tournament_out(tournament)


async def find_organisation(db: AsyncSession, slug: str) -> UUID | None:
    """An organisation's id by slug (seed scripts, share links)."""
    return await repository.organisation_id_by_slug(db, slug)


async def groups_of(db: AsyncSession, tournament_id: UUID) -> list[GroupOut]:
    """A tournament's groups in order (A, B, …)."""
    return [
        GroupOut(id=g.id, name=g.name, order=g.order)
        for g in await repository.groups_of(db, tournament_id)
    ]


async def entries_of(db: AsyncSession, tournament_id: UUID) -> list[EntryOut]:
    """The teams entered in a tournament, with their group and seeding."""
    return [
        EntryOut(
            team_id=entry.team_id,
            name=team.name,
            short_name=team.short_name,
            group_id=entry.group_id,
            seed=entry.seed,
            pot=entry.pot,
            withdrawn=entry.withdrawn_at is not None,
            seed_reason=entry.seeding_reason,
        )
        for entry, team in await repository.entries_of(db, tournament_id)
    ]


async def set_match_teams(
    db: AsyncSession, match_id: UUID, home_team_id: UUID | None, away_team_id: UUID | None
) -> bool:
    """Fill a knockout match's teams once its placeholders resolve; True if they changed."""
    async with transaction(db):
        match = await db.get(Match, match_id)
        if match is None:
            raise NotFound()
        if (match.home_team_id, match.away_team_id) == (home_team_id, away_team_id):
            return False
        match.home_team_id, match.away_team_id = home_team_id, away_team_id
        return True


async def format_spec_of(db: AsyncSession, tournament_id: UUID) -> dict[str, object]:
    """The engine FormatSpec stored at publish."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None or tournament.format_spec is None:
        raise NotFound()
    return tournament.format_spec


async def pitches_of(db: AsyncSession, tournament_id: UUID) -> list[PitchOut]:
    """The pitches a tournament's matches are played on, main pitch first."""
    return [
        PitchOut(id=p.id, name=p.name, is_main=p.is_main)
        for p in await repository.pitches_of(db, tournament_id)
    ]


async def public_tournaments(
    db: AsyncSession,
    *,
    organisation_id: UUID | None = None,
    series_id: UUID | None = None,
    team_id: UUID | None = None,
) -> list[TournamentOut]:
    """Published tournaments (never drafts) of an organisation, a series or a team."""
    rows = await repository.public_tournaments(db, organisation_id, series_id, team_id)
    return [_tournament_out(t) for t in rows]


async def organisation_page(db: AsyncSession, organisation_id: UUID) -> OrganisationPage:
    org = await db.get(Organisation, organisation_id)
    if org is None:
        raise NotFound()
    return OrganisationPage(
        **_organisation_summary(org).model_dump(),
        sponsors=list(org.sponsors or []),
        tournaments=await public_tournaments(db, organisation_id=org.id),
    )


def _organisation_summary(org: Organisation) -> OrganisationSummary:
    return OrganisationSummary(
        id=org.id,
        name=org.name,
        slug=org.slug,
        kind=org.kind,
        town=org.town,
        sports=list(org.sports),
        logo_url=org.logo_url,
        colors=OrganisationColors.model_validate(org.colors) if org.colors else None,
    )


async def series_page(db: AsyncSession, series_id: UUID) -> SeriesPage:
    series = await db.get(TournamentSeries, series_id)
    if series is None:
        raise NotFound()
    return SeriesPage(
        id=series.id,
        name=series.name,
        slug=series.slug,
        sport=series.sport,
        editions=await public_tournaments(db, series_id=series.id),
    )


async def team_matches(db: AsyncSession, team_id: UUID) -> list[MatchOut]:
    """A team's matches in published tournaments, in kick-off order."""
    return [_match_out(m) for m in await repository.team_matches(db, team_id)]


async def update_settings(
    db: AsyncSession, tournament_id: UUID, changes: dict[str, object]
) -> TournamentOut:
    """Change fan-facing settings (languages, live access, probabilities, filming)."""
    async with transaction(db):
        tournament = await db.get(Tournament, tournament_id)
        if tournament is None:
            raise NotFound()
        settings = TournamentSettings.model_validate({**tournament.settings, **changes})
        tournament.settings = settings.model_dump(mode="json")
    return _tournament_out(tournament)


async def apply_schedule(
    db: AsyncSession, clock: Clock, tournament_id: UUID, update_: ScheduleUpdate
) -> int:
    """Move matches, record walkovers and withdrawals; returns the new schedule version."""
    async with transaction(db):
        matches = {m.code: m for m in await repository.matches_of(db, tournament_id)}
        pitches = {p.name: p.id for p in await repository.pitches_of(db, tournament_id)}
        version = max((m.schedule_version for m in matches.values()), default=1) + 1
        for move in update_.moves:
            match = matches[move.code]
            match.starts_at = move.starts_at
            match.pitch_id = pitches[move.pitch]
            match.schedule_version = version
        for code, result in update_.walkovers.items():
            matches[code].result = result
            matches[code].status = "walkover"
        for team_id in update_.withdrawn_team_ids:
            entry = await db.get(TournamentTeam, (tournament_id, team_id))
            if entry is not None:
                entry.withdrawn_at = entry.withdrawn_at or clock.now()
    return version


async def lifecycle_transitions(db: AsyncSession, clock: Clock) -> dict[str, int]:
    """upcoming → active on the first day; active → finished when every match is done (or
    the last day has passed); finished → archived after 30 days (periodic, every 5 min)."""
    today = clock.now().date()
    moved = {"active": 0, "finished": 0, "archived": 0}
    async with transaction(db):
        for t in await repository.tournaments_in(db, ("upcoming", "active", "finished")):
            open_matches = await repository.open_match_count(db, t.id)
            if t.status == "upcoming" and t.starts_on and t.starts_on <= today:
                t.status, moved["active"] = "active", moved["active"] + 1
            elif t.status == "active" and (open_matches == 0 or (t.ends_on and t.ends_on < today)):
                t.status, moved["finished"] = "finished", moved["finished"] + 1
            elif t.status == "finished" and t.ends_on and (today - t.ends_on).days > 30:
                t.status, moved["archived"] = "archived", moved["archived"] + 1
    return moved


async def matches_starting(db: AsyncSession, start: datetime, end: datetime) -> list[MatchOut]:
    """Scheduled matches of published tournaments kicking off in [start, end)."""
    return [_match_out(m) for m in await repository.matches_starting(db, start, end)]


async def names_for_checking(db: AsyncSession, tournament_id: UUID) -> dict[str, list[str]]:
    """Team and player names of a tournament, split by who may read them, for the claim
    checker to block (never served). Players are read as the tournament's staff would see
    them, through the visibility filter."""
    staff = repository.Audience(staff_tournament_ids=frozenset({tournament_id}))
    names: dict[str, list[str]] = {"teams": [], "players": [], "private_players": []}
    for entry in await entries_of(db, tournament_id):
        names["teams"].append(entry.name)
        for p in await repository.visible_players(db, entry.team_id, staff):
            names["players" if p.visibility == "public" else "private_players"].append(
                p.display_name
            )
    return names


# --- participant data rights (organisers, docs/09 GDPR) ------------------------------------

ERASED_PLAYER = "Removed player"


async def _require_manager(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> None:
    if not await manages(db, viewer, tournament_id):
        raise NotFound()


async def participant_data(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID
) -> ParticipantData:
    """Every team contact, player and consent of the tournament (organisers only)."""
    await _require_manager(db, viewer, tournament_id)
    staff = repository.Audience(staff_tournament_ids=frozenset({tournament_id}))
    teams = []
    for entry in await entries_of(db, tournament_id):
        team = await db.get(Team, entry.team_id)
        assert team is not None
        players = []
        for p in await repository.visible_players(db, team.id, staff):
            consents = await repository.consents_of(db, p.id)
            players.append(
                ParticipantPlayer(
                    id=p.id,
                    display_name=p.display_name,
                    shirt_number=p.shirt_number,
                    birth_year=p.birth_year,
                    visibility=p.visibility,
                    consents=[
                        ParticipantConsent(
                            scope=c.scope,
                            guardian_contact=c.guardian_contact,
                            granted_at=c.granted_at,
                            withdrawn_at=c.withdrawn_at,
                        )
                        for c in consents
                    ],
                )
            )
        teams.append(
            ParticipantTeam(
                id=team.id,
                name=team.name,
                contact_name=team.contact_name,
                contact_email=team.contact_email,
                contact_phone=team.contact_phone,
                players=players,
            )
        )
    return ParticipantData(tournament_id=tournament_id, generated_at=clock.now(), teams=teams)


async def _tournament_player(db: AsyncSession, tournament_id: UUID, player_id: UUID) -> Player:
    player = await repository.player_for_update(db, player_id)
    entered = {e.team_id for e in await entries_of(db, tournament_id)}
    if player is None or player.team_id not in entered:
        raise NotFound()
    return player


async def erase_player(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, player_id: UUID
) -> None:
    """Erase a player's personal data on request: the row stays (match events point at
    it) but becomes an anonymous, hidden player without consents or family links."""
    await _require_manager(db, viewer, tournament_id)
    async with transaction(db):
        player = await _tournament_player(db, tournament_id, player_id)
        player.display_name = ERASED_PLAYER
        player.shirt_number = None
        player.birth_year = None
        player.visibility = "hidden"
        await repository.delete_consents(db, player_id)
        await accounts.unlink_player(db, player_id)


async def erase_team_contact(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, team_id: UUID
) -> None:
    """Remove a team's contact person details on request."""
    await _require_manager(db, viewer, tournament_id)
    if team_id not in {e.team_id for e in await entries_of(db, tournament_id)}:
        raise NotFound()
    async with transaction(db):
        team = await db.get(Team, team_id)
        assert team is not None
        team.contact_name = team.contact_email = team.contact_phone = None


# --- processing agreement (docs/13 §7: first setup) ----------------------------------------


async def require_processing_agreement(db: AsyncSession, tournament_id: UUID) -> None:
    """Uploads need the organisation's acceptance of the current processing terms."""
    tournament = await db.get(Tournament, tournament_id)
    if tournament is None:
        raise NotFound()
    if not await repository.has_agreement(db, tournament.organisation_id, PROCESSING_TERMS_VERSION):
        raise ProcessingAgreementRequired(
            f"the organisation must accept the processing terms {PROCESSING_TERMS_VERSION}"
        )


async def accept_processing_agreement(
    db: AsyncSession, clock: Clock, viewer: Viewer, organisation_id: UUID
) -> AgreementOut:
    """Accept the current processing terms for an organisation the viewer runs."""
    assert viewer.user_id is not None
    if not await repository.runs_organisation(db, viewer.user_id, organisation_id):
        raise NotFound()
    now = clock.now()
    async with transaction(db):
        db.add(
            ProcessingAgreement(
                id=new_id(),
                organisation_id=organisation_id,
                version=PROCESSING_TERMS_VERSION,
                accepted_by=viewer.user_id,
                accepted_at=now,
            )
        )
    return AgreementOut(
        organisation_id=organisation_id, version=PROCESSING_TERMS_VERSION, accepted_at=now
    )


# --- rosters (organisers) -----------------------------------------------------------------


def _consent_out(c: Consent) -> ConsentOut:
    return ConsentOut(
        id=c.id,
        scope=c.scope,
        guardian_contact=c.guardian_contact,
        granted_at=c.granted_at,
        withdrawn_at=c.withdrawn_at,
    )


async def _entered_team(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, team_id: UUID
) -> None:
    await _require_manager(db, viewer, tournament_id)
    if team_id not in {e.team_id for e in await entries_of(db, tournament_id)}:
        raise NotFound()


async def roster(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, team_id: UUID
) -> list[RosterPlayer]:
    """Every player of an entered team with their consents (organisers)."""
    await _entered_team(db, viewer, tournament_id, team_id)
    staff = repository.Audience(staff_tournament_ids=frozenset({tournament_id}))
    out = []
    for p in await repository.visible_players(db, team_id, staff):
        consents = [_consent_out(c) for c in await repository.consents_of(db, p.id)]
        out.append(
            RosterPlayer(**_player_out(p).model_dump(), birth_year=p.birth_year, consents=consents)
        )
    return out


async def add_roster_player(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    team_id: UUID,
    data: PlayerCreate,
) -> PlayerOut:
    """Add a player; juniors start hidden (docs/09)."""
    await _entered_team(db, viewer, tournament_id, team_id)
    return await create_player(db, clock, team_id, data)


async def _less_visible(
    db: AsyncSession, tournament_id: UUID, before: str, after: PlayerOut
) -> None:
    """A player became less visible: content that named them is refreshed (docs/09)."""
    if _OPENNESS.index(after.visibility) < _OPENNESS.index(before):
        await jobs.defer(
            db, "refresh_team_content", tournament_id=tournament_id, team_id=after.team_id
        )


async def change_visibility(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    player_id: UUID,
    visibility: Visibility,
) -> PlayerOut:
    await _require_manager(db, viewer, tournament_id)
    before = (await _tournament_player(db, tournament_id, player_id)).visibility
    after = await set_player_visibility(db, clock, player_id, visibility)
    async with transaction(db):
        await _less_visible(db, tournament_id, before, after)
    return after


async def add_consent(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    player_id: UUID,
    data: ConsentCreate,
) -> ConsentOut:
    await _require_manager(db, viewer, tournament_id)
    await _tournament_player(db, tournament_id, player_id)
    consent_id = await record_consent(db, clock, player_id, data)
    consent = await repository.consent_for_update(db, consent_id)
    assert consent is not None
    return _consent_out(consent)


async def remove_consent(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, consent_id: UUID
) -> PlayerOut:
    """Withdraw a consent; visibility drops at once and content is refreshed."""
    await _require_manager(db, viewer, tournament_id)
    consent = await repository.consent_for_update(db, consent_id)
    if consent is None:
        raise NotFound()
    before = (await _tournament_player(db, tournament_id, consent.player_id)).visibility
    after = await withdraw_consent(db, clock, consent_id)
    async with transaction(db):
        await _less_visible(db, tournament_id, before, after)
    return after


async def link_guardian(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    player_id: UUID,
    email: str,
) -> None:
    """Link a guardian's account to a player (they then see `family_only` data)."""
    await _require_manager(db, viewer, tournament_id)
    await _tournament_player(db, tournament_id, player_id)
    user_id = await accounts.user_id_by_email(db, email)
    if user_id is None:
        raise NotFound("no account with this email; ask the guardian to sign up first")
    await accounts.link_family(db, clock, user_id, player_id, viewer.user_id)


async def filming_status(
    db: AsyncSession, clock: Clock, tournament_id: UUID, team_ids: list[UUID]
) -> list[FilmingPlayer]:
    """Each listed player of these teams: junior or not, and whether a filming consent is
    active (the media module's filming check)."""
    staff = repository.Audience(staff_tournament_ids=frozenset({tournament_id}))
    out = []
    for team_id in team_ids:
        team = await db.get(Team, team_id)
        if team is None:
            continue
        for p in await repository.visible_players(db, team_id, staff):
            scopes = await repository.active_consent_scopes(db, p.id)
            out.append(
                FilmingPlayer(
                    player_id=p.id,
                    team_id=team_id,
                    is_junior=_is_junior(p.birth_year, team.age_group, clock.now()),
                    filming_consent="filming" in scopes,
                )
            )
    return out


async def player_team(db: AsyncSession, tournament_id: UUID, player_id: UUID) -> UUID:
    """The entered team of a player of this tournament (NotFound otherwise)."""
    return (await _tournament_player(db, tournament_id, player_id)).team_id


# --- drawing of lots ------------------------------------------------------------------------


async def record_lots(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    group_id: UUID,
    order: list[UUID],
) -> None:
    """Store the order a drawing of lots gave (the latest one per group counts)."""
    await _require_manager(db, viewer, tournament_id)
    entered = {e.team_id for e in await entries_of(db, tournament_id) if e.group_id == group_id}
    if not order or not set(order) <= entered or len(set(order)) != len(order):
        raise ValidationFailed("the drawn order must list teams of this group, once each")
    async with transaction(db):
        db.add(
            LotsDraw(
                tournament_id=tournament_id,
                group_id=group_id,
                order=[str(t) for t in order],
                drawn_by=viewer.user_id,
                created_at=clock.now(),
            )
        )


async def lots_of(db: AsyncSession, tournament_id: UUID) -> dict[UUID | None, list[str]]:
    """The latest drawing of lots per group."""
    return await repository.lots_of(db, tournament_id)


# --- search, organisation teams, settings and staff (T-066) --------------------------------

SEARCH_KINDS = ("organisation", "tournament", "team", "player")


async def search(
    db: AsyncSession,
    q: str,
    kind: str | None,
    sport: str | None,
    region: str | None,
    limit: int = 10,
) -> SearchResult:
    """Find organisations, published tournaments, their teams and public players."""
    kinds = {kind} if kind else set(SEARCH_KINDS)
    found = await repository.search(db, q.strip(), kinds, sport, region, limit)
    hits: list[SearchHit] = []
    hits += [
        SearchHit(type="organisation", id=o.id, name=o.name, detail=o.town)
        for o in found.get("organisation", [])
    ]
    hits += [
        SearchHit(type="tournament", id=t.id, name=t.name, detail=t.sport)
        for t in found.get("tournament", [])
    ]
    hits += [SearchHit(type="team", id=t.id, name=t.name) for t in found.get("team", [])]
    hits += [
        SearchHit(type="player", id=p.id, name=p.display_name, detail=team)
        for p, team in found.get("player", [])
    ]
    return SearchResult(query=q, hits=hits)


async def organisation_teams(db: AsyncSession, organisation_id: UUID) -> list[TeamOut]:
    """An organisation's teams (no contact details)."""
    if await db.get(Organisation, organisation_id) is None:
        raise NotFound()
    return [_team_out(t) for t in await repository.organisation_teams(db, organisation_id)]


async def organisation_tournament_ids(db: AsyncSession, organisation_id: UUID) -> list[UUID]:
    """Published tournaments of an organisation."""
    return [t.id for t in await public_tournaments(db, organisation_id=organisation_id)]


async def tournaments_in(
    db: AsyncSession, region: str | None, limit: int = 30
) -> list[TournamentOut]:
    """Published tournaments (in a town, when given), newest first (public feed)."""
    rows = await repository.published_in_region(db, region, limit)
    return [_tournament_out(t) for t in rows]


_JUNIOR_FILMING = ("consent_required", "not_allowed")


async def change_settings(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, patch: SettingsPatch
) -> TournamentOut:
    """Change fan-facing settings (organisers); juniors film only with consent or not at
    all."""
    await _require_manager(db, viewer, tournament_id)
    tournament = await get_tournament(db, viewer, tournament_id)
    changes: dict[str, object] = patch.model_dump(exclude_none=True)
    policy = changes.get("filming_policy")
    if policy is not None:
        if tournament.is_junior and policy not in _JUNIOR_FILMING:
            raise ValidationFailed(
                "junior tournaments need the filming policy consent_required or not_allowed"
            )
        changes["filming_confirmed"] = True
    return await update_settings(db, tournament_id, changes)


async def list_staff(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> list[StaffOut]:
    await _require_manager(db, viewer, tournament_id)
    out = []
    for s in await repository.staff_of(db, tournament_id):
        name = await accounts.display_name(db, s.user_id)
        out.append(StaffOut(user_id=s.user_id, display_name=name, role=s.role))
    return out


async def invite_staff(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, data: StaffIn
) -> StaffOut:
    """Make an existing account an organiser or scorer of the tournament."""
    await _require_manager(db, viewer, tournament_id)
    user_id = await accounts.user_id_by_email(db, str(data.email))
    if user_id is None:
        raise NotFound("no account with this email; ask them to sign up first")
    current = {s.user_id: s.role for s in await repository.staff_of(db, tournament_id)}
    if current.get(user_id) == "owner":
        raise Conflict("the owner keeps the owner role")
    await add_staff(db, tournament_id, user_id, data.role)
    return StaffOut(
        user_id=user_id, display_name=await accounts.display_name(db, user_id), role=data.role
    )


async def remove_staff(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, user_id: UUID
) -> None:
    await _require_manager(db, viewer, tournament_id)
    staff = {s.user_id: s for s in await repository.staff_of(db, tournament_id)}
    row = staff.get(user_id)
    if row is None:
        raise NotFound()
    if row.role == "owner":
        raise Conflict("the owner cannot be removed")
    async with transaction(db):
        await db.delete(row)


# --- catalogue lists for the front end (T-066) ----------------------------------------------


def _name_after(params: PageParams) -> tuple[str, UUID] | None:
    if not params.cursor:
        return None
    position = decode_cursor(params.cursor)
    try:
        return str(position["name"]), UUID(str(position["id"]))
    except (KeyError, ValueError):
        raise ValidationFailed("Invalid pagination cursor") from None


def _next(rows: list[Any], params: PageParams, position: dict[str, CursorValue]) -> str | None:
    return encode_cursor(position) if len(rows) > params.limit else None


async def list_sports(db: AsyncSession) -> list[SportOut]:
    """The sports OurSport can run (football and futsal in this release)."""
    return [SportOut(code=s.code, name=s.name) for s in await repository.sports(db)]


async def list_organisations(
    db: AsyncSession, params: PageParams, sport: str | None = None
) -> Page[OrganisationSummary]:
    """Every organisation, by name."""
    rows = await repository.organisations_page(db, _name_after(params), params.limit + 1, sport)
    items = rows[: params.limit]
    last = items[-1] if items else None
    cursor = _next(rows, params, {"name": last.name, "id": str(last.id)}) if last else None
    return Page(items=[_organisation_summary(o) for o in items], next_cursor=cursor)


async def list_tournaments(
    db: AsyncSession,
    params: PageParams,
    *,
    organisation_id: UUID | None = None,
    sport: str | None = None,
    status: str | None = None,
) -> Page[TournamentListItem]:
    """Published tournaments (never drafts), newest first."""
    after = None
    if params.cursor:
        position = decode_cursor(params.cursor)
        try:
            after = (date.fromisoformat(str(position["starts"])), UUID(str(position["id"])))
        except (KeyError, ValueError):
            raise ValidationFailed("Invalid pagination cursor") from None
    rows = await repository.published_page(
        db, after, params.limit + 1, organisation_id, sport, status
    )
    items = rows[: params.limit]
    names = await repository.organisation_names(db, {t.organisation_id for t in items})
    counts = await repository.team_counts(db, [t.id for t in items])
    out = [
        TournamentListItem(
            **_tournament_out(t).model_dump(),
            organisation_name=names.get(t.organisation_id, ""),
            team_count=counts.get(t.id, 0),
        )
        for t in items
    ]
    cursor = None
    if items and len(rows) > params.limit:
        last = items[-1]
        starts = (last.starts_on or repository.EPOCH).isoformat()
        cursor = encode_cursor({"starts": starts, "id": str(last.id)})
    return Page(items=out, next_cursor=cursor)


async def list_teams(
    db: AsyncSession,
    params: PageParams,
    *,
    tournament_id: UUID | None = None,
    organisation_id: UUID | None = None,
) -> Page[TeamListItem]:
    """Teams of published tournaments, by name, with the tournaments they play in."""
    rows = await repository.published_teams_page(
        db, _name_after(params), params.limit + 1, tournament_id, organisation_id
    )
    items = rows[: params.limit]
    entries = await repository.published_entries_of_teams(db, [t.id for t in items])
    where: dict[UUID, list[Tournament]] = {}
    for team_id, tournament in entries:
        where.setdefault(team_id, []).append(tournament)
    out = [
        TeamListItem(
            **_team_out(t).model_dump(exclude={"contacts"}),
            sports=sorted({x.sport for x in where.get(t.id, [])}),
            tournament_ids=[x.id for x in where.get(t.id, [])],
        )
        for t in items
    ]
    last = items[-1] if items else None
    cursor = _next(rows, params, {"name": last.name, "id": str(last.id)}) if last else None
    return Page(items=out, next_cursor=cursor)


async def me_parts(db: AsyncSession, user_id: UUID) -> MeParts:
    """The user's tournament staff roles and the organisations they run (for `GET /me`)."""
    staff = await repository.staff_roles_of(db, user_id)
    org_ids = set(await repository.agreed_organisations(db, user_id))
    org_ids |= {t.organisation_id for role, t in staff if role in repository.MANAGING_ROLES}
    names = await repository.organisation_names(db, org_ids)
    return MeParts(
        memberships=[
            Membership(organisation_id=oid, organisation_name=names.get(oid, ""), role="admin")
            for oid in sorted(org_ids, key=lambda o: names.get(o, ""))
        ],
        staff_tournaments=[
            StaffTournament(
                tournament_id=t.id,
                tournament_name=t.name,
                organisation_id=t.organisation_id,
                role=role,
            )
            for role, t in staff
        ],
    )


def register() -> None:
    """Fill the staff part of `GET /me`."""
    accounts.contribute_to_me("competitions", me_parts)


async def organisation_names(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    """Organisation id -> name."""
    return await repository.organisation_names(db, ids)


async def managed_tournaments(db: AsyncSession, viewer: Viewer) -> list[TournamentOut]:
    """Tournaments the viewer owns or organises (any status)."""
    if viewer.user_id is None:
        return []
    return [
        _tournament_out(t)
        for role, t in await repository.staff_roles_of(db, viewer.user_id)
        if role in repository.MANAGING_ROLES
    ]
