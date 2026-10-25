"""Analysis: runs the engine after every result and stores the read models fans see.

`recalc_tournament` computes standings, the bracket (writing resolved teams into the
knockout matches), scenarios, relevance, team journeys and final placements. It skips when
nothing it reads has changed (source hash). `recalc_live` projects the table "if it ended
now" and skips when a newer event of the same match is already stored, so a burst of
events costs one recalculation.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db import transaction
from app.core.errors import ValidationFailed
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.analysis import facts, insights, ratings, reads
from app.modules.analysis.models import (
    AnalysisVersion,
    BracketSnapshot,
    FinalPlacement,
    RelevanceSnapshot,
    ScenarioSnapshot,
    StandingsSnapshot,
    TeamJourney,
)
from app.modules.analysis.schemas import (
    FactSheetOut,
    MatchCard,
    MatchInfo,
    PlayerPage,
    ScreenPage,
    StandingsPage,
    TeamHub,
    TeamName,
)
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import EntryOut, GroupOut, MatchOut, TournamentOut
from app.modules.rules import service as rules
from app.modules.scoring import service as scoring
from engine.bracket import Bracket, BracketResolution, build_bracket, resolve_bracket
from engine.model import Fixture, MatchResult, TeamRef, TournamentState
from engine.relevance import match_relevance
from engine.rules.config import RuleConfig
from engine.rules.format import FormatSpec
from engine.scenarios import compute_scenarios
from engine.sports.football import FootballResult
from engine.standings import StandingRow, Standings, compute_standings

fact_payload = facts.fact_payload  # the JSON a writing task sends (content)

SCENARIO_BRANCHES = 20_000
SCENARIO_SAMPLES = 300


@dataclass(frozen=True)
class Loaded:
    tournament: TournamentOut
    rules: RuleConfig
    rule_version: int
    fmt: FormatSpec
    groups: list[GroupOut]
    entries: list[EntryOut]
    matches: list[MatchOut]
    lots: dict[UUID | None, list[str]]

    @property
    def group_names(self) -> dict[UUID, str]:
        return {g.id: g.name for g in self.groups}


async def _load(db: AsyncSession, tournament_id: UUID) -> Loaded:
    tournament = await competitions.tournament_window(db, tournament_id)
    confirmed = await rules.confirmed_config(db, tournament_id)
    fmt_data = await competitions.format_spec_of(db, tournament_id)
    return Loaded(
        tournament=tournament,
        rules=RuleConfig.model_validate(confirmed.config),
        rule_version=confirmed.version,
        fmt=FormatSpec.model_validate(fmt_data),
        groups=await competitions.groups_of(db, tournament_id),
        entries=await competitions.entries_of(db, tournament_id),
        matches=await competitions.list_matches(db, tournament_id),
        lots=await competitions.lots_of(db, tournament_id),
    )


def _result(data: dict[str, Any]) -> FootballResult:
    return FootballResult(
        int(data["home_goals"]),
        int(data["away_goals"]),
        data.get("decided_by", "regulation"),
        data.get("home_penalties"),
        data.get("away_penalties"),
    )


def _match_result(m: MatchOut, group: str | None, outcome: FootballResult) -> MatchResult:
    assert m.home_team_id is not None and m.away_team_id is not None
    return MatchResult(
        str(m.id),
        group,
        str(m.home_team_id),
        str(m.away_team_id),
        outcome,
        starts_at=m.starts_at.isoformat(),
    )


def _state(
    loaded: Loaded, provisional: dict[UUID, FootballResult] | None = None
) -> TournamentState:
    names = loaded.group_names
    groups: dict[str | None, tuple[str, ...]] = {
        g.name: tuple(str(e.team_id) for e in loaded.entries if e.group_id == g.id)
        for g in loaded.groups
    }
    results, fixtures = [], []
    for m in loaded.matches:
        if m.stage != "group" or m.home_team_id is None or m.away_team_id is None:
            continue
        group = names.get(m.group_id) if m.group_id else None
        if m.status == "finished" and m.result:
            results.append(_match_result(m, group, _result(m.result)))
        elif provisional and m.id in provisional:
            results.append(_match_result(m, group, provisional[m.id]))
        else:
            fixtures.append(
                Fixture(
                    str(m.id),
                    group,
                    str(m.home_team_id),
                    str(m.away_team_id),
                    m.starts_at.isoformat(),
                )
            )
    teams = tuple(TeamRef(str(e.team_id), e.name) for e in loaded.entries)
    lots: dict[str | None, tuple[str, ...]] = {
        names[g]: tuple(order) for g, order in loaded.lots.items() if g in names
    }
    return TournamentState(
        teams, groups, tuple(results), tuple(fixtures), loaded.rules, loaded.fmt, lots
    )


def _knockout_results(loaded: Loaded) -> dict[str, MatchResult]:
    return {
        m.code: _match_result(m, None, _result(m.result))
        for m in loaded.matches
        if m.stage != "group"
        and m.status == "finished"
        and m.result
        and m.home_team_id
        and m.away_team_id
    }


def _source_version(loaded: Loaded) -> str:
    payload = {
        "rules": loaded.rule_version,
        "entries": sorted((str(e.team_id), str(e.group_id), e.withdrawn) for e in loaded.entries),
        "matches": sorted(
            (
                str(m.id),
                m.status,
                json.dumps(m.result, sort_keys=True),
                str(m.home_team_id),
                str(m.away_team_id),
            )
            for m in loaded.matches
        ),
        "lots": sorted((str(g), order) for g, order in loaded.lots.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# --- serialisation ---------------------------------------------------------------------------


def _row(row: StandingRow) -> dict[str, Any]:
    s = row.stats
    return {
        "position": row.position,
        "team_id": row.team,
        "played": s.played,
        "won": s.won,
        "drawn": s.drawn,
        "lost": s.lost,
        "goals_for": s.score_for,
        "goals_against": s.score_against,
        "goal_difference": s.score_diff,
        "points": s.points,
        "form": list(row.form),
        "decided_by": row.decided_by.value if row.decided_by else None,
        "tied_unresolved": row.tied_unresolved,
    }


def _bracket_json(resolution: BracketResolution) -> dict[str, Any]:
    def slot(s: Any) -> dict[str, Any]:
        return {
            "source": s.source,
            "status": s.status,
            "team_id": s.team,
            "could_be": list(s.could_be),
            "blocked_reason": s.blocked_reason,
        }

    return {
        "matches": [
            {"code": m.code, "round": m.round, "home": slot(m.home), "away": slot(m.away)}
            for m in resolution.matches
        ]
    }


def _final_placements(loaded: Loaded, standings: Standings) -> list[tuple[str, int, str]]:
    """(team, placement, stage reached) once the final is played; [] before."""
    by_code = {m.code: m for m in loaded.matches}
    final = by_code.get("F")
    if final is None or final.status != "finished" or not final.result:
        return []
    placed: dict[str, tuple[int, str]] = {}

    def winner_loser(m: MatchOut) -> tuple[str, str]:
        r = _result(m.result or {})
        home_wins = (r.home_goals, r.home_penalties or 0) > (r.away_goals, r.away_penalties or 0)
        h, a = str(m.home_team_id), str(m.away_team_id)
        return (h, a) if home_wins else (a, h)

    w, loser = winner_loser(final)
    placed[w], placed[loser] = (1, "final"), (2, "final")
    third = by_code.get("3P")
    if third and third.status == "finished" and third.result:
        w3, l3 = winner_loser(third)
        placed[w3], placed[l3] = (3, "semi_final"), (4, "semi_final")
    next_place = {"semi_final": 3, "quarter_final": 5, "round_of_16": 9}
    for stage in ("semi_final", "quarter_final", "round_of_16"):
        for m in loaded.matches:
            if m.stage == stage and m.status == "finished" and m.result:
                _, beaten = winner_loser(m)
                placed.setdefault(beaten, (next_place[stage], stage))
    rank = len(placed) + 1
    rest = sorted(
        (row for group in standings.groups for row in group.rows if row.team not in placed),
        key=lambda r: (r.position, -r.stats.points, -r.stats.score_diff),
    )
    for row in rest:
        placed[row.team] = (rank, "group")
    return [(team, place, stage) for team, (place, stage) in placed.items()]


# --- recalculation ---------------------------------------------------------------------------


async def recalc_tournament(
    db: AsyncSession, clock: Clock, tournament_id: UUID, *, force: bool = False
) -> bool:
    """Recompute every read model; False when nothing has changed since the last run."""
    loaded = await _load(db, tournament_id)
    source = _source_version(loaded)
    current = await db.get(AnalysisVersion, tournament_id)
    if current is not None and current.source_version == source and not force:
        return False
    knockout = _knockout_results(loaded)
    state = _state(loaded)
    standings = compute_standings(state)
    bracket: Bracket | None = None
    filled = False
    if loaded.fmt.knockout is not None:
        bracket = build_bracket(loaded.fmt, loaded.rules.advancement)
        resolution = resolve_bracket(bracket, state, knockout_results=knockout)
        by_code = {m.code: m for m in loaded.matches}
        for r in resolution.matches:
            match = by_code.get(r.code)
            if match is None or match.status not in ("scheduled", "postponed"):
                continue
            home = UUID(r.home.team) if r.home.team else match.home_team_id
            away = UUID(r.away.team) if r.away.team else match.away_team_id
            if await competitions.set_match_teams(db, match.id, home, away):
                filled = True
                if home and away:  # both teams known: tell them who they play next
                    await jobs.defer(
                        db, "notify_followers", kind="next_opponent", match_id=match.id
                    )
                    await _write(db, "match", match.id, "preview")
    if filled:  # the knockout teams are part of what was read
        loaded = await _load(db, tournament_id)
        source = _source_version(loaded)
    previous = await _previous_team_views(db, tournament_id, current.version if current else None)
    now = clock.now()
    version = (current.version if current else 0) + 1
    group_ids = {g.name: g.id for g in loaded.groups}
    async with transaction(db):
        await ratings.update_ratings(db, loaded.tournament, loaded.entries, loaded.matches, now)
        await ratings.predict_fixtures(
            db, loaded.tournament, loaded.entries, loaded.matches, standings, version, now
        )
        for group in standings.groups:
            db.add(
                StandingsSnapshot(
                    tournament_id=tournament_id,
                    group_id=group_ids.get(str(group.group_id)),
                    version=version,
                    source_version=source,
                    provisional=False,
                    rows=[_row(r) for r in group.rows],
                    computed_at=now,
                )
            )
        if bracket is not None:
            resolution = resolve_bracket(
                bracket, _state(loaded), knockout_results=_knockout_results(loaded)
            )
            db.add(
                BracketSnapshot(
                    tournament_id=tournament_id,
                    version=version,
                    bracket=_bracket_json(resolution),
                    computed_at=now,
                )
            )
        state = _state(loaded)
        team_ratings = await insights.ratings_of(
            db,
            [e.team_id for e in loaded.entries],
            loaded.tournament.sport,
            loaded.tournament.age_group,
        )
        await insights.store_comparisons(db, loaded.matches, team_ratings, version, now)
        tournament_chances = insights.chances(state, team_ratings, bracket)
        status_after: dict[str, str] = {}
        for entry in loaded.entries:
            team = str(entry.team_id)
            if entry.group_id is None:
                continue
            scenario = compute_scenarios(
                state,
                team,
                bracket=bracket,
                knockout_results=_knockout_results(loaded),
                max_branches=SCENARIO_BRANCHES,
                samples=SCENARIO_SAMPLES,
            )
            db.add(
                ScenarioSnapshot(
                    tournament_id=tournament_id,
                    team_id=entry.team_id,
                    version=version,
                    scenario={
                        **_scenario_json(scenario),
                        "chances": tournament_chances.get(team),
                    },
                    computed_at=now,
                )
            )
            if scenario.knockout is None and scenario.status not in ("clinched", "eliminated"):
                items = match_relevance(state, team, max_branches=SCENARIO_BRANCHES)
            else:
                items = []
            db.add(
                RelevanceSnapshot(
                    tournament_id=tournament_id,
                    team_id=entry.team_id,
                    version=version,
                    items=[_relevance_json(i) for i in items[:10]],
                    computed_at=now,
                )
            )
            await _notify_changes(db, tournament_id, entry.team_id, scenario, items, previous)
            status_after[team] = scenario.status
            await db.merge(
                TeamJourney(
                    tournament_id=tournament_id,
                    team_id=entry.team_id,
                    version=version,
                    journey=_journey(loaded, team, standings),
                    computed_at=now,
                )
            )
        analysed, corrected = await insights.store_analyses(
            db,
            state,
            loaded.matches,
            {str(e.team_id): e.name for e in loaded.entries},
            int(loaded.rules.match.get("periods", 2))
            * int(loaded.rules.match.get("period_minutes", 20)),
            {str(t): status for t, (status, _) in previous.items() if status},
            status_after,
            version,
            now,
        )
        await _story_jobs(db, loaded, analysed, corrected, previous, status_after)
        for team, place, stage in _final_placements(loaded, standings):
            await db.merge(
                FinalPlacement(
                    tournament_id=tournament_id,
                    team_id=UUID(team),
                    placement=place,
                    stage_reached=stage,
                    computed_at=now,
                )
            )
        if current is None:
            db.add(
                AnalysisVersion(
                    tournament_id=tournament_id,
                    version=version,
                    source_version=source,
                    live_seq={},
                    computed_at=now,
                )
            )
        else:
            current.version, current.source_version, current.computed_at = version, source, now
    return True


async def _write(db: AsyncSession, subject_type: str, subject_id: UUID, kind: str) -> None:
    await jobs.defer(
        db, "write_story", subject_type=subject_type, subject_id=str(subject_id), kind=kind
    )


async def _story_jobs(
    db: AsyncSession,
    loaded: Loaded,
    analysed: list[MatchOut],
    corrected: list[MatchOut],
    previous: dict[UUID, tuple[str | None, str | None]],
    status_after: dict[str, str],
) -> None:
    """Content's writing jobs (docs/07, Writing tasks): a report and a result announcement
    per newly finished match, a corrected report when a result changed, a recap for each
    team that is out, and the summary."""
    tournament_id = loaded.tournament.id
    for m in corrected:
        await jobs.defer(
            db, "write_story", subject_type="match", subject_id=str(m.id), kind="report",
            correction=True,
        )  # fmt: skip
    for m in analysed:
        await _write(db, "match", m.id, "report")
        await jobs.defer(
            db, "draft_announcement", tournament_id=str(tournament_id), kind="result", ref=str(m.id)
        )
        if m.stage != "group" and m.code not in ("F", "3P") and m.result:
            r = _result(m.result)
            home_won = (r.home_goals, r.home_penalties or 0) > (r.away_goals, r.away_penalties or 0)
            loser = m.away_team_id if home_won else m.home_team_id
            if loser:
                await jobs.defer(
                    db, "write_story", subject_type="team", subject_id=str(loser),
                    kind="team_recap", tournament_id=str(tournament_id),
                )  # fmt: skip
    for team, status in status_after.items():
        if status == "eliminated" and previous.get(UUID(team), (None, []))[0] != "eliminated":
            await jobs.defer(
                db, "write_story", subject_type="team", subject_id=team, kind="team_recap",
                tournament_id=str(tournament_id),
            )  # fmt: skip
    final = next((m for m in analysed if m.code == "F"), None)
    if final is not None:
        await _write(db, "tournament", tournament_id, "summary")
        for m in loaded.matches:
            if m.code in ("F", "3P"):
                for team_id in (m.home_team_id, m.away_team_id):
                    if team_id:
                        await jobs.defer(
                            db, "write_story", subject_type="team", subject_id=str(team_id),
                            kind="team_recap", tournament_id=str(tournament_id),
                        )  # fmt: skip


def _scenario_json(s: Any) -> dict[str, Any]:
    return {
        "status": s.status,
        "exact": s.exact,
        "qualify_share": round(s.qualify_share, 4),
        "paths": [
            {
                "outcome": p.outcome,
                "result": p.result,
                "summary": p.summary,
                "share": round(p.share, 4),
            }
            for p in s.paths
        ],
        "knockout": None
        if s.knockout is None
        else {
            "next_match": s.knockout.next_match,
            "opponent": s.knockout.opponent,
            "opponent_could_be": list(s.knockout.opponent_could_be),
            "route": list(s.knockout.route),
            "eliminated_in": s.knockout.eliminated_in,
        },
    }


def _relevance_json(item: Any) -> dict[str, Any]:
    return {
        "match_id": item.match_id,
        "impact": item.impact,
        "best_outcome": item.best_outcome,
        "reason": item.reason,
    }


def _journey(loaded: Loaded, team: str, standings: Standings) -> dict[str, Any]:
    played = []
    for m in loaded.matches:
        if team not in (str(m.home_team_id), str(m.away_team_id)) or not m.result:
            continue
        home = str(m.home_team_id) == team
        r = m.result
        played.append(
            {
                "match_id": str(m.id),
                "code": m.code,
                "stage": m.stage,
                "opponent": str(m.away_team_id if home else m.home_team_id),
                "for": r["home_goals"] if home else r["away_goals"],
                "against": r["away_goals"] if home else r["home_goals"],
            }
        )
    position = next(
        (row.position for g in standings.groups for row in g.rows if row.team == team), None
    )
    return {"results": played, "group_position": position}


async def recalc_live(db: AsyncSession, clock: Clock, match_id: UUID, seq: int) -> bool:
    """The group table "if it ended now"; False when a newer event will recompute it."""
    snapshot = await scoring.live_snapshot(db, match_id)
    if snapshot is None or snapshot[0] > seq:
        return False
    match = await competitions.get_match(db, match_id)
    current = await db.get(AnalysisVersion, match.tournament_id)
    if current is not None and current.live_seq.get(str(match_id), 0) >= seq:
        return False
    if match.stage != "group" or match.group_id is None:
        return True  # knockout: nothing provisional to tabulate
    loaded = await _load(db, match.tournament_id)
    live = snapshot[1]
    standings = compute_standings(
        _state(loaded, {match_id: FootballResult(live.home_goals, live.away_goals)})
    )
    group_name = loaded.group_names[match.group_id]
    group = next(g for g in standings.groups if g.group_id == group_name)
    now = clock.now()
    async with transaction(db):
        db.add(
            StandingsSnapshot(
                tournament_id=match.tournament_id,
                group_id=match.group_id,
                version=current.version if current else 0,
                source_version=f"live:{match_id}:{seq}",
                provisional=True,
                rows=[_row(r) for r in group.rows],
                computed_at=now,
            )
        )
        if current is None:
            db.add(
                AnalysisVersion(
                    tournament_id=match.tournament_id,
                    version=0,
                    source_version="",
                    live_seq={str(match_id): seq},
                    computed_at=now,
                )
            )
        else:
            current.live_seq = {**current.live_seq, str(match_id): seq}
    return True


async def latest_standings(db: AsyncSession, tournament_id: UUID) -> list[StandingsSnapshot]:
    """The latest confirmed table of every group (fan reads, T-033)."""
    current = await db.get(AnalysisVersion, tournament_id)
    if current is None:
        return []
    result = await db.execute(
        select(StandingsSnapshot).where(
            StandingsSnapshot.tournament_id == tournament_id,
            StandingsSnapshot.version == current.version,
            StandingsSnapshot.provisional.is_(False),
        )
    )
    return list(result.scalars())


async def all_standings(db: AsyncSession, tournament_id: UUID) -> list[StandingsSnapshot]:
    """Every standings snapshot, oldest first (audits and tests)."""
    result = await db.execute(
        select(StandingsSnapshot)
        .where(StandingsSnapshot.tournament_id == tournament_id)
        .order_by(StandingsSnapshot.computed_at, StandingsSnapshot.id)
    )
    return list(result.scalars())


async def team_hub(
    db: AsyncSession, viewer: Viewer, team_id: UUID, tournament_id: UUID | None = None
) -> TeamHub:
    """The My Team hub for one team (audience composes /me/home from this)."""
    return await reads.team_hub(db, viewer, team_id, tournament_id)


async def tournament_results(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID
) -> list[MatchCard]:
    """Finished matches of a tournament, newest first (public feed)."""
    page = await reads.schedule_page(db, viewer, tournament_id)
    done = [m for m in page.matches if m.status in ("finished", "walkover")]
    return sorted(done, key=lambda m: m.starts_at, reverse=True)


async def team_cards(db: AsyncSession, viewer: Viewer, team_id: UUID) -> list[MatchCard]:
    """A team's matches as fan cards (live score per the live access policy)."""
    return (await reads.team_page(db, viewer, team_id)).matches


async def tournament_cards(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID
) -> list[MatchCard]:
    """Every match of a tournament as fan cards."""
    return (await reads.schedule_page(db, viewer, tournament_id)).matches


RELEVANCE_ALERT = 0.3


async def _previous_team_views(
    db: AsyncSession, tournament_id: UUID, version: int | None
) -> dict[UUID, tuple[str | None, str | None]]:
    """(scenario status, top relevant match) per team at the previous version."""
    if version is None:
        return {}
    views: dict[UUID, tuple[str | None, str | None]] = {}
    for s in (
        await db.execute(
            select(ScenarioSnapshot).where(
                ScenarioSnapshot.tournament_id == tournament_id, ScenarioSnapshot.version == version
            )
        )
    ).scalars():
        views[s.team_id] = (s.scenario.get("status"), None)
    for r in (
        await db.execute(
            select(RelevanceSnapshot).where(
                RelevanceSnapshot.tournament_id == tournament_id,
                RelevanceSnapshot.version == version,
            )
        )
    ).scalars():
        top = (
            r.items[0]["match_id"] if r.items and r.items[0]["impact"] >= RELEVANCE_ALERT else None
        )
        views[r.team_id] = (views.get(r.team_id, (None, None))[0], top)
    return views


async def _notify_changes(
    db: AsyncSession,
    tournament_id: UUID,
    team_id: UUID,
    scenario: Any,
    items: list[Any],
    previous: dict[UUID, tuple[str | None, str | None]],
) -> None:
    """Defer scenario-change and relevance notifications when what a team needs changed."""
    if not previous:
        return  # the first computation is the baseline, not news
    status, top = previous.get(team_id, (None, None))
    if scenario.status != status:
        summary = scenario.paths[0].summary if scenario.paths else scenario.status
        await jobs.defer(
            db,
            "notify_followers",
            kind="scenario_change",
            tournament_id=tournament_id,
            team_ids=str(team_id),
            summary=summary,
        )
    best = items[0] if items and items[0].impact >= RELEVANCE_ALERT else None
    if best is not None and best.match_id != top:
        await jobs.defer(
            db,
            "notify_followers",
            kind="relevance",
            tournament_id=tournament_id,
            team_ids=str(team_id),
            match=best.match_id,
            reason=best.reason,
        )


async def match_fact_sheet(
    db: AsyncSession, clock: Clock, match_id: UUID, kind: str
) -> FactSheetOut | None:
    """Fact sheet for a match `preview` or `report` (content's writing tasks, T-052)."""
    match = await competitions.get_match(db, match_id)
    tables = await latest_standings(db, match.tournament_id)
    return await facts.match_fact_sheet(db, clock, match_id, kind, tables)


async def team_fact_sheet(
    db: AsyncSession, clock: Clock, tournament_id: UUID, team_id: UUID
) -> FactSheetOut:
    """Fact sheet for a team recap."""
    tables = await latest_standings(db, tournament_id)
    return await facts.team_fact_sheet(db, clock, tournament_id, team_id, tables)


async def tournament_fact_sheet(
    db: AsyncSession, clock: Clock, tournament_id: UUID
) -> FactSheetOut:
    """Fact sheet for a tournament summary."""
    tables = await latest_standings(db, tournament_id)
    return await facts.tournament_fact_sheet(db, clock, tournament_id, tables)


async def names_for_checking(db: AsyncSession, tournament_id: UUID) -> dict[str, list[str]]:
    """Team and player names for the claim checker (content); never served."""
    return await competitions.names_for_checking(db, tournament_id)


async def manages(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> bool:
    """Whether the viewer runs this tournament (owner, organiser or organisation admin)."""
    return await competitions.manages(db, viewer, tournament_id)


async def visible_tournament(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID
) -> TournamentOut:
    """The tournament if this viewer may see it (NotFound otherwise)."""
    return await competitions.get_tournament(db, viewer, tournament_id)


async def match_tournament_id(db: AsyncSession, match_id: UUID) -> UUID:
    """The tournament a match belongs to (NotFound for an unknown match)."""
    return (await competitions.get_match(db, match_id)).tournament_id


async def fact_sheet(db: AsyncSession, sheet_id: UUID) -> FactSheetOut | None:
    """A stored fact sheet by id."""
    return await facts.load(db, sheet_id)


async def live_fact_sheet(
    db: AsyncSession, clock: Clock, match_id: UUID, since_seq: int, moments: list[str]
) -> FactSheetOut | None:
    """Fact sheet for live commentary, with the "if it ended now" table of the group."""
    match = await competitions.get_match(db, match_id)
    snapshots = await all_standings(db, match.tournament_id)
    latest: dict[UUID | None, StandingsSnapshot] = {}
    for s in snapshots:  # oldest first: the last one of each group wins
        if s.group_id == match.group_id:
            latest[s.group_id] = s
    return await facts.live_fact_sheet(
        db, clock, match_id, since_seq, moments, list(latest.values())
    )


def _info(m: MatchOut) -> MatchInfo:
    return MatchInfo.model_validate(m.model_dump())


async def live_matches(db: AsyncSession, tournament_id: UUID) -> list[MatchInfo]:
    """Matches of a tournament that are live now (commentary priority)."""
    matches = await competitions.list_matches(db, tournament_id)
    return [_info(m) for m in matches if m.status == "live"]


async def can_watch_live(db: AsyncSession, viewer: Viewer, match_id: UUID) -> bool:
    """Whether the live access policy lets this viewer follow the match live."""
    match = await competitions.get_match(db, match_id)
    tournament = await competitions.get_tournament(db, viewer, match.tournament_id)
    return match.status != "live" or await reads.can_watch_live(db, viewer, tournament)


async def match_info(db: AsyncSession, match_id: UUID) -> MatchInfo:
    """A match (teams, stage, status) for content's live work."""
    return _info(await competitions.get_match(db, match_id))


async def live_seq(db: AsyncSession, match_id: UUID) -> int:
    """The last event seq of a match (0 before kick-off)."""
    snapshot = await scoring.live_snapshot(db, match_id)
    return snapshot[0] if snapshot else 0


async def team_names(db: AsyncSession, tournament_id: UUID) -> dict[str, str]:
    """Team id -> name of a tournament's entries."""
    return {str(e.team_id): e.name for e in await competitions.entries_of(db, tournament_id)}


async def match_card(db: AsyncSession, viewer: Viewer, match_id: UUID) -> MatchCard:
    """A match as fans see it (share cards)."""
    return (await reads.match_page(db, viewer, match_id)).match


async def screen(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> ScreenPage:
    """The venue screen read model (content adds commentary and announcements)."""
    return await reads.screen_page(db, viewer, tournament_id)


# --- players, team and organisation matches, drawing of lots (T-066) -----------------------

_GOAL_EVENTS = ("goal", "penalty_goal")


async def player_page(db: AsyncSession, viewer: Viewer, player_id: UUID) -> PlayerPage:
    """A player page (404 for anyone the visibility filter hides them from)."""
    player = await competitions.get_player(db, viewer, player_id)
    team = await competitions.get_team(db, viewer, player.team_id)
    goals = 0
    for m in await competitions.team_matches(db, player.team_id):
        if m.status not in ("live", "finished") or m.data_level != "events":
            continue
        scorers = await scoring.scorers(db, m.id)
        for e in await scoring.timeline(db, m.id):
            if e["type"] in _GOAL_EVENTS and not e["undone"] and scorers.get(e["seq"]) == player.id:
                goals += 1
    tournaments = await competitions.public_tournaments(db, team_id=player.team_id)
    return PlayerPage(
        id=player.id,
        display_name=player.display_name,
        shirt_number=player.shirt_number,
        team=TeamName(id=team.id, name=team.name),
        goals=goals,
        tournaments=[{"id": str(t.id), "name": t.name} for t in tournaments],
    )


async def organisation_matches(
    db: AsyncSession, viewer: Viewer, organisation_id: UUID, when: str | None, clock: Clock
) -> list[MatchCard]:
    """Matches of an organisation's tournaments: `live`, `today`, `upcoming` or `recent`."""
    cards: list[MatchCard] = []
    for tid in await competitions.organisation_tournament_ids(db, organisation_id):
        cards += await tournament_cards(db, viewer, tid)
    return _when(cards, when, clock)


async def resolve_lots(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    group_id: UUID,
    order: list[UUID],
) -> StandingsPage:
    """Record a drawing of lots for the teams still tied in a group, then recompute."""
    table = next(
        (s for s in await latest_standings(db, tournament_id) if s.group_id == group_id), None
    )
    tied = {r["team_id"] for r in (table.rows if table else []) if r["tied_unresolved"]}
    if not tied:
        raise ValidationFailed("no teams in this group are waiting for a drawing of lots")
    if {str(t) for t in order} != tied:
        raise ValidationFailed(f"draw lots for exactly the tied teams: {sorted(tied)}")
    await competitions.record_lots(db, clock, viewer, tournament_id, group_id, order)
    await recalc_tournament(db, clock, tournament_id)
    return await reads.standings_page(db, viewer, tournament_id)


_FEED_STATUSES = ("upcoming", "active", "finished")


async def all_matches(
    db: AsyncSession, viewer: Viewer, clock: Clock, when: str | None
) -> list[MatchCard]:
    """Matches of every published, not archived tournament (`when` as for organisations):
    the fan app's feed of live scores, fixtures and results."""
    cards: list[MatchCard] = []
    for t in await competitions.public_tournaments(db):
        if t.status in _FEED_STATUSES:
            cards += await tournament_cards(db, viewer, t.id)
    return _when(cards, when, clock)


def _when(cards: list[MatchCard], when: str | None, clock: Clock) -> list[MatchCard]:
    now = clock.now()
    if when == "live":
        cards = [c for c in cards if c.status == "live"]
    elif when == "today":
        cards = [c for c in cards if c.starts_at.date() == now.date()]
    elif when == "upcoming":
        cards = [c for c in cards if c.status == "scheduled" and c.starts_at >= now][:50]
    elif when == "recent":
        done = [c for c in cards if c.status in ("finished", "walkover")]
        return sorted(done, key=lambda c: c.starts_at, reverse=True)[:50]
    return sorted(cards, key=lambda c: c.starts_at)


async def organisation_tournament_ids(db: AsyncSession, organisation_id: UUID) -> list[UUID]:
    """Published tournaments of an organisation (404 for an unknown one)."""
    await competitions.organisation_page(db, organisation_id)
    return await competitions.organisation_tournament_ids(db, organisation_id)
