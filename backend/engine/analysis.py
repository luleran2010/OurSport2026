"""What decided a match (docs/04-engine.md, Match analysis): facts for stories and the
match page. Every fact carries the value it rests on; nothing is guessed."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from engine.model import EventLite
from engine.sports.football import FootballResult

UPSET_CHANCE = 0.35
LATE_MINUTES = 5


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str  # result, comeback, late_winner, upset, table, qualified, eliminated
    claim: str
    value: float | int | str | None
    team: str | None


def _minute(event: EventLite) -> int | None:
    minute = event.payload.get("minute")
    return minute if isinstance(minute, int) else None


def analyse_match(
    home: str,
    away: str,
    events: Sequence[EventLite],
    result: FootballResult,
    *,
    names: Mapping[str, str],
    match_minutes: int,
    win_chance: Mapping[str, float] | None = None,  # pre-match chance per team
    position_before: Mapping[str, int] | None = None,
    position_after: Mapping[str, int] | None = None,
    status_before: Mapping[str, str] | None = None,
    status_after: Mapping[str, str] | None = None,
) -> list[Fact]:
    facts: list[Fact] = []

    def add(kind: str, claim: str, value: float | int | str | None, team: str | None) -> None:
        facts.append(Fact(f"f{len(facts) + 1}", kind, claim, value, team))

    n = {t: names.get(t, t) for t in (home, away)}
    add(
        "result",
        f"{n[home]} {result.home_goals}-{result.away_goals} {n[away]}",
        f"{result.home_goals}-{result.away_goals}",
        None,
    )
    winner = (
        home
        if result.home_goals > result.away_goals
        else away
        if result.away_goals > result.home_goals
        else None
    )

    undone = {e.payload.get("undoes_seq") for e in events if e.type == "undo"}
    goals = [
        e for e in sorted(events, key=lambda e: e.seq) if e.type == "goal" and e.seq not in undone
    ]
    score = {home: 0, away: 0}
    worst = {home: 0, away: 0}  # biggest deficit each team faced
    decisive: EventLite | None = None
    for goal in goals:
        scorer = (
            goal.team
            if goal.payload.get("kind") != "own_goal"
            else (away if goal.team == home else home)
        )
        if scorer not in score:
            continue
        before_lead = score[home] - score[away]
        score[scorer] += 1
        after_lead = score[home] - score[away]
        worst[home] = max(worst[home], -after_lead)
        worst[away] = max(worst[away], after_lead)
        if (
            winner
            and scorer == winner
            and (before_lead == 0 or (before_lead > 0) != (winner == home))
        ):
            decisive = goal  # the goal that put the winner ahead for good (last such goal)
    if winner and worst[winner] >= 1:
        add(
            "comeback",
            f"{n[winner]} came back from {worst[winner]} down to win",
            worst[winner],
            winner,
        )
    elif winner is None and max(worst.values()) >= 2:
        team = home if worst[home] >= 2 else away
        add("comeback", f"{n[team]} fought back from {worst[team]} down to draw", worst[team], team)
    if winner and decisive is not None:
        minute = _minute(decisive)
        if minute is not None and minute >= match_minutes - LATE_MINUTES:
            add("late_winner", f"{n[winner]} scored the winner in minute {minute}", minute, winner)
    if winner and win_chance and win_chance.get(winner, 1.0) < UPSET_CHANCE:
        chance = round(win_chance[winner], 2)
        add(
            "upset", f"{n[winner]} won as underdogs (pre-match chance {chance:.0%})", chance, winner
        )
    for team in (home, away):
        before = (position_before or {}).get(team)
        after = (position_after or {}).get(team)
        if before is not None and after is not None and before != after:
            add("table", f"{n[team]} moved from {before} to {after} in the group", after, team)
        status = (status_after or {}).get(team)
        if status and status != (status_before or {}).get(team):
            if status == "clinched":
                add("qualified", f"{n[team]} are through", status, team)
            elif status == "eliminated":
                add("eliminated", f"{n[team]} are out", status, team)
    return facts
