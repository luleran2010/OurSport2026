"""Ratings after each result and predictions for every known fixture (docs/04, ADR 0005).

Runs inside `recalc_tournament`. Each finished match updates both teams once
(`rating_history` is the ledger); a team's first match in a new tournament carries its
rating over from the previous one. Single-venue tournaments: no home advantage.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analysis.models import PredictionRecord, Rating, RatingHistory
from app.modules.competitions.schemas import EntryOut, MatchOut, TournamentOut
from engine.predictions import MatchContext, Prediction, placement_label, predict_match
from engine.ratings import RatingInfo, carry_over, prior, update
from engine.standings import Standings


def _info(row: Rating) -> RatingInfo:
    return RatingInfo(str(row.team_id), row.rating, row.games, row.prior_source)  # type: ignore[arg-type]  # one of the prior sources


async def _rating(
    db: AsyncSession,
    team_id: UUID,
    tournament: TournamentOut,
    entry: EntryOut | None,
    now: datetime,
) -> Rating:
    row = await db.get(Rating, (team_id, tournament.sport, tournament.age_group))
    if row is None:
        info = prior(str(team_id), pot=entry.pot if entry else None)
        row = Rating(
            team_id=team_id,
            sport=tournament.sport,
            age_group=tournament.age_group,
            rating=info.rating,
            games=0,
            prior_source=info.prior_source,
            last_tournament_id=tournament.id,
            updated_at=now,
        )
        db.add(row)
    elif row.last_tournament_id != tournament.id:
        carried = carry_over(_info(row), junior=tournament.is_junior)
        row.rating, row.prior_source, row.last_tournament_id = (
            carried.rating,
            carried.prior_source,
            tournament.id,
        )
    return row


async def update_ratings(
    db: AsyncSession,
    tournament: TournamentOut,
    entries: list[EntryOut],
    matches: list[MatchOut],
    now: datetime,
) -> int:
    """Apply every finished, not yet rated match in kick-off order; returns how many."""
    by_team = {e.team_id: e for e in entries}
    done = {
        r.match_id
        for r in (
            await db.execute(
                select(RatingHistory).where(RatingHistory.match_id.in_([m.id for m in matches]))
            )
        ).scalars()
    }
    applied = 0
    for m in sorted(matches, key=lambda m: m.starts_at):
        if (
            m.status != "finished"
            or not m.result
            or m.id in done
            or not (m.home_team_id and m.away_team_id)
        ):
            continue  # walkovers never change ratings
        home = await _rating(db, m.home_team_id, tournament, by_team.get(m.home_team_id), now)
        away = await _rating(db, m.away_team_id, tournament, by_team.get(m.away_team_id), now)
        result = m.result
        new_home, new_away = update(
            _info(home),
            _info(away),
            int(str(result["home_goals"])),
            int(str(result["away_goals"])),
            penalties=result.get("decided_by") == "penalties",
        )
        for row, new in ((home, new_home), (away, new_away)):
            db.add(
                RatingHistory(
                    team_id=row.team_id,
                    match_id=m.id,
                    before=row.rating,
                    after=new.rating,
                    created_at=now,
                )
            )
            row.rating, row.games, row.updated_after_match_id, row.updated_at = (
                new.rating,
                new.games,
                m.id,
                now,
            )
        await db.flush()
        applied += 1
    return applied


def _position_text(standings: Standings, team: str) -> str | None:
    for group in standings.groups:
        for row in group.rows:
            if row.team == team and row.stats.played:
                suffix = (
                    "th"
                    if 10 <= row.position % 100 <= 20
                    else {1: "st", 2: "nd", 3: "rd"}.get(row.position % 10, "th")
                )
                return f"{row.position}{suffix} in Group {group.group_id}"
    return None


async def predict_fixtures(
    db: AsyncSession,
    tournament: TournamentOut,
    entries: list[EntryOut],
    matches: list[MatchOut],
    standings: Standings,
    version: int,
    now: datetime,
) -> int:
    """Store a prediction for every scheduled match whose teams are known."""
    by_team = {e.team_id: e for e in entries}
    forms = {r.team: r.form for g in standings.groups for r in g.rows}
    year = tournament.starts_on.year - 1 if tournament.starts_on else None
    count = 0
    for m in matches:
        if m.status not in ("scheduled", "postponed") or not (m.home_team_id and m.away_team_id):
            continue
        home = _info(
            await _rating(db, m.home_team_id, tournament, by_team.get(m.home_team_id), now)
        )
        away = _info(
            await _rating(db, m.away_team_id, tournament, by_team.get(m.away_team_id), now)
        )
        seeding = {}
        for side, team_id in (("home", m.home_team_id), ("away", m.away_team_id)):
            reason = (by_team[team_id].seed_reason or {}) if team_id in by_team else {}
            label = placement_label(reason.get("previous_placement"), year)  # type: ignore[arg-type]  # stored as an int
            if label:
                seeding[side] = label
        ctx = MatchContext(
            knockout=m.stage != "group",
            seeding=seeding,
            form={
                "home": forms.get(str(m.home_team_id), ()),
                "away": forms.get(str(m.away_team_id), ()),
            },
            positions={
                side: text
                for side, team in (("home", m.home_team_id), ("away", m.away_team_id))
                if (text := _position_text(standings, str(team)))
            },
        )
        await _store(db, m.id, predict_match(home, away, ctx), version, now)
        count += 1
    return count


async def _store(
    db: AsyncSession, match_id: UUID, p: Prediction, version: int, now: datetime
) -> None:
    await db.merge(
        PredictionRecord(
            match_id=match_id,
            version=version,
            home_win_low=p.home_win[0],
            home_win_high=p.home_win[1],
            draw_low=p.draw[0] if p.draw else None,
            draw_high=p.draw[1] if p.draw else None,
            away_win_low=p.away_win[0],
            away_win_high=p.away_win[1],
            confidence=p.confidence,
            factors=[
                {"id": f.id, "kind": f.kind, "team": f.team, "text": f.text} for f in p.factors
            ],
            model_version=p.model_version,
            computed_at=now,
        )
    )
