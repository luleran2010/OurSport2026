"""Comparisons before a match, analysis after it, tournament chances (docs/04)."""

import dataclasses
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analysis.models import MatchAnalysis, PredictionRecord, Rating, TeamComparison
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut
from app.modules.scoring import service as scoring
from engine.analysis import analyse_match
from engine.bracket import Bracket
from engine.comparison import compare_teams
from engine.model import EventLite, MatchResult, TournamentState
from engine.ratings import RatingInfo
from engine.simulation import simulate
from engine.sports.football import FootballResult
from engine.standings import Standings, compute_standings

SIMULATION_RUNS = 2_000


def _result(m: MatchOut) -> FootballResult:
    r = m.result or {}
    penalties = (r.get("home_penalties"), r.get("away_penalties"))
    return FootballResult(
        int(str(r["home_goals"])),
        int(str(r["away_goals"])),
        str(r.get("decided_by", "regulation")),  # type: ignore[arg-type]  # stored from a FootballResult
        int(str(penalties[0])) if penalties[0] is not None else None,
        int(str(penalties[1])) if penalties[1] is not None else None,
    )


async def ratings_of(
    db: AsyncSession, team_ids: list[UUID], sport: str, age_group: str
) -> dict[str, RatingInfo]:
    out = {}
    for team in team_ids:
        row = await db.get(Rating, (team, sport, age_group))
        if row is not None:
            out[str(team)] = RatingInfo(str(team), row.rating, row.games, row.prior_source)  # type: ignore[arg-type]  # a prior source
    return out


async def _history(db: AsyncSession, team_ids: list[UUID]) -> list[MatchResult]:
    """Finished matches of these teams in every published tournament (previous editions too)."""
    seen: dict[UUID, MatchResult] = {}
    for team in team_ids:
        for m in await competitions.team_matches(db, team):
            if m.status == "finished" and m.result and m.home_team_id and m.away_team_id:
                seen[m.id] = MatchResult(
                    str(m.id),
                    None,
                    str(m.home_team_id),
                    str(m.away_team_id),
                    _result(m),
                    starts_at=m.starts_at.isoformat(),
                )
    return list(seen.values())


async def store_comparisons(
    db: AsyncSession,
    matches: list[MatchOut],
    ratings: dict[str, RatingInfo],
    version: int,
    now: datetime,
) -> None:
    for m in matches:
        if m.status not in ("scheduled", "postponed") or not (m.home_team_id and m.away_team_id):
            continue
        history = await _history(db, [m.home_team_id, m.away_team_id])
        c = compare_teams(history, str(m.home_team_id), str(m.away_team_id), ratings=ratings)
        await db.merge(
            TeamComparison(
                match_id=m.id, version=version, comparison=dataclasses.asdict(c), computed_at=now
            )
        )


def _positions(standings: Standings) -> dict[str, int]:
    return {row.team: row.position for g in standings.groups for row in g.rows}


async def store_analyses(
    db: AsyncSession,
    state: TournamentState,
    matches: list[MatchOut],
    names: dict[str, str],
    match_minutes: int,
    status_before: dict[str, str],
    status_after: dict[str, str],
    version: int,
    now: datetime,
) -> tuple[list[MatchOut], list[MatchOut]]:
    """Facts for every finished match without them, and again for a match whose result or
    events were corrected since; returns (newly analysed, corrected) matches."""
    after = _positions(compute_standings(state))
    analysed: list[MatchOut] = []
    corrected: list[MatchOut] = []
    for m in matches:
        if m.status != "finished" or not m.result or not (m.home_team_id and m.away_team_id):
            continue
        stored = await db.get(MatchAnalysis, m.id)
        basis = {"result": m.result, "last_seq": m.last_seq}
        if stored is not None and stored.analysis.get("basis", basis) == basis:
            continue
        home, away = str(m.home_team_id), str(m.away_team_id)
        events = [
            EventLite(
                seq=e["seq"],
                type="undo" if e["undone"] else e["type"],
                team=e["team_id"],
                payload={
                    **e["payload"],
                    "minute": int(str(e["clock"]).split(":")[0]) if e["clock"] else None,
                },
            )
            for e in await scoring.timeline(db, m.id)
        ]
        # Undone events are marked; drop them rather than replaying undo pointers.
        events = [e for e in events if e.type != "undo"]
        before_state = dataclasses.replace(
            state, results=tuple(r for r in state.results if r.match_id != str(m.id))
        )
        before = _positions(compute_standings(before_state)) if m.stage == "group" else {}
        prediction = await db.get(PredictionRecord, m.id)
        chance = None
        if prediction is not None:
            chance = {
                home: (prediction.home_win_low + prediction.home_win_high) / 2,
                away: (prediction.away_win_low + prediction.away_win_high) / 2,
            }
        facts = analyse_match(
            home,
            away,
            events,
            _result(m),
            names=names,
            match_minutes=match_minutes,
            win_chance=chance,
            position_before=before or None,
            position_after={t: after[t] for t in (home, away) if t in after}
            if m.stage == "group"
            else None,
            status_before=status_before,
            status_after=status_after,
        )
        await db.merge(
            MatchAnalysis(
                match_id=m.id,
                version=version,
                analysis={"facts": [dataclasses.asdict(f) for f in facts], "basis": basis},
                computed_at=now,
            )
        )
        (analysed if stored is None else corrected).append(m)
    return analysed, corrected


def chances(
    state: TournamentState, ratings: dict[str, RatingInfo], bracket: Bracket | None
) -> dict[str, dict[str, Any]]:
    """Per team: qualify, win the group, reach each round, win the cup."""
    result = simulate(state, ratings, bracket=bracket, runs=SIMULATION_RUNS, seed=b"recalc")
    return {
        team: {
            "qualify": round(c.qualify, 3),
            "win_group": round(c.win_group, 3),
            "reach": {k: round(v, 3) for k, v in c.reach.items()},
            "win": round(c.win, 3),
        }
        for team, c in result.items()
    }
