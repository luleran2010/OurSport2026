"""Fact builder (docs/07-content-pipeline.md, Fact sheets).

Builds the only input a writing task gets: numbered facts taken from the read models
(standings, analyses, predictions, scenarios, journeys, placements) and the event log.
Team names are always used; a player is named only if the visibility filter shows them
to an anonymous viewer (`public`), so hidden and family-only players never appear. No
emails, birth years or contact details are ever read here.

Sheets are stored once per distinct input (`inputs_hash`), which is also the cache and
idempotency key of the writing task.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.analysis.models import (
    FactSheet,
    FinalPlacement,
    MatchAnalysis,
    PredictionRecord,
    ScenarioSnapshot,
    StandingsSnapshot,
    TeamJourney,
)
from app.modules.analysis.schemas import Fact, FactContext, FactSheetOut
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut, TournamentOut
from app.modules.scoring import service as scoring

FACTS_VERSION = "facts-1"
ANONYMOUS = Viewer()
_PLACES = {1: "won the tournament", 2: "finished runner-up", 3: "finished third"}
_GOALS = ("goal", "own_goal", "penalty_goal")
_CARDS = ("red_card", "second_yellow")
_EVENT_CLAIMS = {
    "goal": "scored",
    "penalty_goal": "scored a penalty",
    "own_goal": "were given an own goal",
    "red_card": "were shown a red card",
    "second_yellow": "were shown a red card",
    "penalty_missed": "missed a penalty",
    "foul": "committed a foul",
    "timeout": "called a timeout",
}
_MOMENT_CLAIMS = {
    "equaliser": "{team} equalised",
    "lead_change": "{team} took the lead",
    "kick_off": "Kick-off: {home} against {away}",
    "half_time": "Half time",
    "full_time": "Full time",
    "sixth_foul": "{team} have six accumulated fouls: direct free kicks from now on",
    "timeout": "{team} called a timeout",
}


class _Sheet:
    """Numbers facts f1, f2, … in the order they are added."""

    def __init__(self) -> None:
        self.facts: list[Fact] = []

    def add(
        self,
        kind: str,
        claim: str,
        source: str,
        value: int | float | str | None = None,
        *,
        unit: str | None = None,
        team: UUID | str | None = None,
    ) -> None:
        self.facts.append(
            Fact(
                id=f"f{len(self.facts) + 1}",
                kind=kind,
                claim=claim,
                value=value,
                unit=unit,
                source=source,
                team_id=str(team) if team else None,
            )
        )


def _context(tournament: TournamentOut) -> FactContext:
    settings = tournament.settings
    return FactContext(
        tournament_id=tournament.id,
        is_junior=tournament.is_junior,
        show_probabilities=settings.show_probabilities,
        languages=list(settings.languages),
        tone_profile="junior" if tournament.is_junior else "adult",
    )


def _hash(subject: str, kind: str, facts: Sequence[Fact], context: FactContext) -> str:
    payload = {
        "version": FACTS_VERSION,
        "subject": subject,
        "kind": kind,
        "facts": [f.model_dump() for f in facts],
        "context": context.model_dump(),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def _store(
    db: AsyncSession,
    clock: Clock,
    subject_type: str,
    subject_id: UUID,
    kind: str,
    sheet: _Sheet,
    context: FactContext,
) -> FactSheetOut:
    """The stored sheet for these inputs; an unchanged input returns the existing row."""
    inputs_hash = _hash(f"{subject_type}:{subject_id}", kind, sheet.facts, context)
    row = await db.scalar(select(FactSheet).where(FactSheet.inputs_hash == inputs_hash))
    if row is None:
        row = FactSheet(
            subject_type=subject_type,
            subject_id=subject_id,
            kind=kind,
            facts=[f.model_dump(mode="json") for f in sheet.facts],
            context=context.model_dump(mode="json"),
            inputs_hash=inputs_hash,
            created_at=clock.now(),
        )
        db.add(row)
        await db.flush()
    return _sheet_out(row)


def _sheet_out(row: FactSheet) -> FactSheetOut:
    return FactSheetOut(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        kind=row.kind,
        facts=[Fact.model_validate(f) for f in row.facts],
        context=FactContext.model_validate(row.context),
        inputs_hash=row.inputs_hash,
        created_at=row.created_at,
    )


async def _names(db: AsyncSession, tournament_id: UUID) -> dict[str, str]:
    return {str(e.team_id): e.name for e in await competitions.entries_of(db, tournament_id)}


async def _public_players(db: AsyncSession, team_ids: Sequence[UUID]) -> dict[UUID, str]:
    """Names of the players an anonymous viewer may see: the visibility filter decides."""
    names: dict[UUID, str] = {}
    for team_id in team_ids:
        for p in await competitions.list_players(db, ANONYMOUS, team_id):
            names[p.id] = p.display_name
    return names


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _standing_facts(
    sheet: _Sheet,
    tables: Sequence[StandingsSnapshot],
    group_names: dict[UUID, str],
    names: dict[str, str],
    teams: Sequence[str],
) -> None:
    for table in tables:
        group = group_names.get(table.group_id) if table.group_id else None
        for row in table.rows:
            team = row["team_id"]
            if team not in teams:
                continue
            where = f"Group {group}" if group else "the table"
            sheet.add(
                "position",
                f"{names[team]} are {_ordinal(row['position'])} in {where}"
                f" with {row['points']} points from {row['played']} matches",
                f"standings_snapshot:v{table.version}",
                row["position"],
                team=team,
            )


def _score_claim(m: MatchOut, names: dict[str, str]) -> tuple[str, str]:
    r = m.result or {}
    home, away = names[str(m.home_team_id)], names[str(m.away_team_id)]
    claim = f"{home} {r.get('home_goals')}-{r.get('away_goals')} {away}"
    if r.get("decided_by") == "penalties":
        claim += f" ({r.get('home_penalties')}-{r.get('away_penalties')} on penalties)"
    return claim, f"{r.get('home_goals')}-{r.get('away_goals')}"


def _minute(e: dict[str, Any]) -> int | None:
    return int(str(e["clock"]).split(":")[0]) if e["clock"] else None


async def _goal_facts(
    db: AsyncSession,
    sheet: _Sheet,
    m: MatchOut,
    names: dict[str, str],
    since_seq: int = 0,
    *,
    live: bool = False,
    discipline: bool = False,
) -> None:
    """Goals (and, live, red cards and missed penalties) after `since_seq`, in order, with
    the player's name only when the player is public."""
    assert m.home_team_id and m.away_team_id
    players = await _public_players(db, [m.home_team_id, m.away_team_id])
    scorer_ids = await scoring.scorers(db, m.id)
    for e in await scoring.timeline(db, m.id, since_seq):
        wanted = _EVENT_CLAIMS if live else (*_GOALS, *(_CARDS if discipline else ()))
        if e["undone"] or e["type"] not in wanted:
            continue
        team = e["team_id"]
        minute = _minute(e)
        when = f" in minute {minute}" if minute is not None else ""
        player_id = scorer_ids.get(e["seq"])
        player = players.get(player_id) if player_id else None
        if e["type"] in ("goal", "penalty_goal"):
            who = f"{player} scored for {names[team]}" if player else f"{names[team]} scored"
        else:
            who = f"{names[team]} {_EVENT_CLAIMS[e['type']]}"
        source = f"match_event:{m.id}:{e['seq']}"
        kind = "goal" if e["type"] in _GOALS else e["type"]
        sheet.add(kind, f"{who}{when}", source, minute, unit="minute", team=team)


async def match_fact_sheet(
    db: AsyncSession,
    clock: Clock,
    match_id: UUID,
    kind: str,
    tables: Sequence[StandingsSnapshot],
) -> FactSheetOut | None:
    """Facts for a match `preview` or `report`; None when the teams are not known yet
    (or a report is asked for before the result)."""
    m = await competitions.get_match(db, match_id)
    if not (m.home_team_id and m.away_team_id) or (kind == "report" and not m.result):
        return None
    tournament = await competitions.tournament_window(db, m.tournament_id)
    context = _context(tournament)
    names = await _names(db, m.tournament_id)
    group_names = {g.id: g.name for g in await competitions.groups_of(db, m.tournament_id)}
    home, away = str(m.home_team_id), str(m.away_team_id)
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, m.tournament_id)}
    sheet = _Sheet()
    stage = f"Group {group_names[m.group_id]}" if m.group_id else m.stage.replace("_", " ")
    source = f"match:{m.id}"
    kickoff = m.starts_at.isoformat()
    sheet.add("fixture", f"{names[home]} play {names[away]} ({stage})", source, m.code)
    sheet.add("kickoff", f"Kick-off {kickoff}", source, kickoff, unit="utc")
    if m.pitch_id in pitches:
        sheet.add("pitch", f"Played on {pitches[m.pitch_id]}", source)

    if kind == "report":
        claim, score = _score_claim(m, names)
        sheet.add("result", claim, f"match:{m.id}", score)
        await _goal_facts(db, sheet, m, names, discipline=True)
        analysis = await db.get(MatchAnalysis, m.id)
        if analysis is not None:
            for f in analysis.analysis["facts"]:
                if f["kind"] == "result":
                    continue  # already stated from the match row
                source = f"match_analysis:v{analysis.version}"
                sheet.add(f["kind"], f["claim"], source, f["value"], team=f["team"])
    else:
        prediction = await db.get(PredictionRecord, m.id)
        if prediction is not None:
            source = f"prediction:v{prediction.version}"
            for factor in prediction.factors:
                side = factor.get("team")
                team = home if side == "home" else away if side == "away" else None
                label = f"{names[team]}: " if team else ""
                sheet.add("reason", f"{label}{factor['text']}", source, team=team)
            if context.show_probabilities and prediction.confidence != "none":
                for team, low, high in (
                    (home, prediction.home_win_low, prediction.home_win_high),
                    (away, prediction.away_win_low, prediction.away_win_high),
                ):
                    sheet.add(
                        "win_chance",
                        f"{names[team]} win chance {round(low * 100)}-{round(high * 100)}%",
                        source,
                        f"{round(low * 100)}-{round(high * 100)}",
                        unit="percent",
                        team=team,
                    )
    if m.group_id:
        _standing_facts(sheet, tables, group_names, names, [home, away])
    return await _store(db, clock, "match", m.id, kind, sheet, context)


async def live_fact_sheet(
    db: AsyncSession,
    clock: Clock,
    match_id: UUID,
    since_seq: int,
    moments: Sequence[str],
    tables: Sequence[StandingsSnapshot],
) -> FactSheetOut | None:
    """Facts for live `commentary`: the score now, what happened after `since_seq`, the
    moments, and the table if the match ended now. None before kick-off."""
    m = await competitions.get_match(db, match_id)
    snapshot = await scoring.live_snapshot(db, match_id)
    if snapshot is None or not (m.home_team_id and m.away_team_id):
        return None
    tournament = await competitions.tournament_window(db, m.tournament_id)
    names = await _names(db, m.tournament_id)
    group_names = {g.id: g.name for g in await competitions.groups_of(db, m.tournament_id)}
    home, away = str(m.home_team_id), str(m.away_team_id)
    seq, score = snapshot
    sheet = _Sheet()
    goals = f"{score.home_goals}-{score.away_goals}"
    sheet.add("score", f"{names[home]} {goals} {names[away]}", f"live_state:{m.id}:{seq}", goals)
    await _goal_facts(db, sheet, m, names, since_seq, live=True)
    # The team of a moment is the team of the latest event (the goal, the sixth foul, …).
    last_team = next((f.team_id for f in reversed(sheet.facts) if f.team_id), None)
    for moment in moments:
        template = _MOMENT_CLAIMS.get(moment)
        if template is None or ("{team}" in template and last_team is None):
            continue
        claim = template.format(
            team=names.get(last_team or "", ""), home=names[home], away=names[away]
        )
        sheet.add("moment", claim, f"live_state:{m.id}:{seq}", moment, team=last_team)
    if m.group_id:
        group = group_names[m.group_id]
        for table in tables:
            if table.group_id != m.group_id:
                continue
            for row in table.rows:
                if row["team_id"] in (home, away):
                    team, place = row["team_id"], row["position"]
                    where = f"{_ordinal(place)} in Group {group}"
                    claim = f"If it ended now, {names[team]} would be {where}"
                    source = f"standings_snapshot:v{table.version}"
                    sheet.add("position", claim, source, place, team=team)
    context = _context(tournament)
    return await _store(db, clock, "match", m.id, "commentary", sheet, context)


async def team_fact_sheet(
    db: AsyncSession,
    clock: Clock,
    tournament_id: UUID,
    team_id: UUID,
    tables: Sequence[StandingsSnapshot],
) -> FactSheetOut:
    """Facts for a `team_recap`: results, group position, scenario and final placement."""
    tournament = await competitions.tournament_window(db, tournament_id)
    names = await _names(db, tournament_id)
    group_names = {g.id: g.name for g in await competitions.groups_of(db, tournament_id)}
    team = str(team_id)
    sheet = _Sheet()
    journey = await db.scalar(
        select(TeamJourney)
        .where(TeamJourney.tournament_id == tournament_id, TeamJourney.team_id == team_id)
        .order_by(TeamJourney.version.desc())
        .limit(1)
    )
    if journey is not None:
        for r in journey.journey["results"]:
            score = f"{r['for']}-{r['against']}"
            outcome = (
                "beat"
                if r["for"] > r["against"]
                else "drew with"
                if r["for"] == r["against"]
                else "lost to"
            )
            opponent = names.get(r["opponent"], "their opponents")
            claim = f"{names[team]} {outcome} {opponent} {score}"
            sheet.add("result", claim, f"team_journey:v{journey.version}", score, team=team)
    _standing_facts(sheet, tables, group_names, names, [team])
    scenario = await db.scalar(
        select(ScenarioSnapshot)
        .where(ScenarioSnapshot.tournament_id == tournament_id, ScenarioSnapshot.team_id == team_id)
        .order_by(ScenarioSnapshot.version.desc())
        .limit(1)
    )
    if scenario is not None:
        status = scenario.scenario["status"]
        claim = f"{names[team]}: {status.replace('_', ' ')}"
        sheet.add("status", claim, f"scenario_snapshot:v{scenario.version}", status, team=team)
    placement = await db.get(FinalPlacement, (tournament_id, team_id))
    if placement is not None:
        stage = placement.stage_reached.replace("_", " ")
        words = _PLACES.get(placement.placement, f"reached the {stage}")
        claim = f"{names[team]} {words}"
        sheet.add("placement", claim, "final_placements", placement.placement, team=team)
    return await _store(db, clock, "team", team_id, "team_recap", sheet, _context(tournament))


async def tournament_fact_sheet(
    db: AsyncSession, clock: Clock, tournament_id: UUID, tables: Sequence[StandingsSnapshot]
) -> FactSheetOut:
    """Facts for a tournament `summary`: podium, group winners, matches and goals."""
    tournament = await competitions.tournament_window(db, tournament_id)
    names = await _names(db, tournament_id)
    group_names = {g.id: g.name for g in await competitions.groups_of(db, tournament_id)}
    sheet = _Sheet()
    placements = (
        await db.scalars(
            select(FinalPlacement)
            .where(FinalPlacement.tournament_id == tournament_id, FinalPlacement.placement <= 3)
            .order_by(FinalPlacement.placement)
        )
    ).all()
    for p in placements:
        claim = f"{names[str(p.team_id)]} {_PLACES[p.placement]}"
        sheet.add("placement", claim, "final_placements", p.placement, team=p.team_id)
    for table in sorted(tables, key=lambda t: group_names.get(t.group_id or t.id, "")):
        if table.rows and table.group_id:
            top = table.rows[0]["team_id"]
            claim = f"{names[top]} won Group {group_names[table.group_id]}"
            sheet.add("group_winner", claim, f"standings_snapshot:v{table.version}", team=top)
    results = [m.result for m in await competitions.list_matches(db, tournament_id) if m.result]
    goals = sum(int(str(r["home_goals"])) + int(str(r["away_goals"])) for r in results)
    source = f"tournament:{tournament_id}"
    played = len(results)
    sheet.add("matches_played", f"{played} matches played", source, played, unit="matches")
    sheet.add("goals", f"{goals} goals scored", source, goals, unit="goals")
    return await _store(
        db, clock, "tournament", tournament_id, "summary", sheet, _context(tournament)
    )


async def load(db: AsyncSession, sheet_id: UUID) -> FactSheetOut | None:
    """A stored fact sheet (stories show the facts behind each sentence)."""
    row = await db.get(FactSheet, sheet_id)
    return _sheet_out(row) if row else None


_SENT = {"id", "kind", "claim", "value", "unit"}


def fact_payload(sheet: FactSheetOut) -> dict[str, Any]:
    """The JSON a writing task sends to the gateway: the facts (without sources and ids,
    which the model does not need and whose digit runs can look like phone numbers to the
    PII guard) and the writing context."""
    return {
        "facts": [f.model_dump(include=_SENT, exclude_none=True) for f in sheet.facts],
        "context": sheet.context.model_dump(mode="json", exclude={"tournament_id"}),
    }
