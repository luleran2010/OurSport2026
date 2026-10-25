"""What a team needs: qualification scenarios (docs/04-engine.md, Scenarios).

The remaining fixtures that can affect the team (its group; every group when best-of-the-
rest places exist) are enumerated outcome by outcome (win/draw/loss, one representative
score each) when there are at most `max_branches` completions, otherwise sampled.

Each completion is judged two ways:
- by points alone, which no score can change: *surely through* when fewer teams than the
  qualifying places can reach the team's points, *surely out* when enough teams have
  strictly more. `clinched` and `eliminated` use only these, so they never mislead;
- by the full table at the representative scores, for shares and paths. Where a tie on
  points is decided by margins, a threshold search finds the margin of each other match
  that flips the answer ("a draw is enough unless A2 beat A3 by 2 or more").

Once the team has a place in the knockout, the scenario is its bracket path.
"""

import dataclasses
import itertools
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from engine.bracket import Bracket, resolve_bracket
from engine.model import Fixture, MatchResult, SportResult, TournamentState
from engine.rng import DeterministicRng
from engine.rules.format import winner_source
from engine.sports.base import SportModule
from engine.sports.registry import get_sport
from engine.standings import StandingRow, Standings, compute_standings

MAX_BRANCHES = 1_000_000
SAMPLES = 2_000
MAX_PATHS = 4

type Status = Literal["clinched", "eliminated", "in_control", "must_win", "alive"]
type Side = Literal["home", "draw", "away"]
type PathResult = Literal["through", "out", "depends"]
# Probability of each representative outcome of a fixture (from predictions, later).
type OutcomeWeights = Callable[[Fixture], Sequence[float]]


@dataclass(frozen=True)
class Condition:
    match_id: str
    outcome: Side
    winner: str | None  # None for a draw
    min_margin: int = 1  # "win by N or more"


@dataclass(frozen=True)
class ScenarioPath:
    outcome: str | None  # the team's next result ("win"/"draw"/"loss"); None: no match left
    match_id: str | None
    result: PathResult
    share: float  # of the other completions in which the team goes through
    unless: tuple[Condition, ...]  # margins elsewhere that flip `result`
    through_if: tuple[Condition, ...]  # for "depends": results that guarantee going through
    out_if: tuple[Condition, ...]  # for "depends": results that mean going out
    summary: str


@dataclass(frozen=True)
class KnockoutPath:
    next_match: str | None  # None after winning the final, or once eliminated
    opponent: str | None
    opponent_could_be: tuple[str, ...]
    route: tuple[str, ...]  # next match to the final
    eliminated_in: str | None


@dataclass(frozen=True)
class Scenario:
    team: str
    status: Status
    exact: bool
    completions: int  # enumerated (or sampled) completions
    qualify_share: float  # share of them in which the team goes through
    paths: tuple[ScenarioPath, ...]
    knockout: KnockoutPath | None = None


# --- enumeration -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Completion:
    choices: tuple[int, ...]  # index into each fixture's options
    value: float  # 1 through, 0 out, 0.5 only lots decide
    sure_in: bool
    sure_out: bool


@dataclass(frozen=True)
class _Table:
    """Every completion of the fixtures that matter to one team."""

    team: str
    fixtures: tuple[Fixture, ...]
    options: tuple[tuple[SportResult, ...], ...]
    completions: tuple[_Completion, ...]
    exact: bool


class _Judge:
    def __init__(self, state: TournamentState, team: str) -> None:
        self.state = state
        self.team = team
        self.sport: SportModule = get_sport(state.rules.sport)
        advancement = state.rules.advancement
        self.cut = max(advancement.per_group, 1)
        self.best_of_rest = advancement.best_of_rest
        self.group = next(g for g, members in state.groups.items() if team in members)
        groups = state.groups if self.best_of_rest else {self.group: state.groups[self.group]}
        self.groups = dict(groups)
        self.base = [r for r in state.results if r.group_id in self.groups]

    def relevant(self) -> list[Fixture]:
        return sorted(
            (
                f
                for f in self.state.fixtures
                if f.group_id in self.groups and f.home is not None and f.away is not None
            ),
            key=lambda f: (f.starts_at, f.match_id),
        )

    def result(self, fixture: Fixture, outcome: SportResult) -> MatchResult:
        assert fixture.home is not None and fixture.away is not None
        return MatchResult(fixture.match_id, fixture.group_id, fixture.home, fixture.away, outcome)

    def standings(self, extra: Sequence[MatchResult]) -> Standings:
        state = dataclasses.replace(
            self.state, groups=self.groups, results=(*self.base, *extra), fixtures=()
        )
        return compute_standings(state)

    def judge(self, extra: Sequence[MatchResult]) -> tuple[float, bool, bool]:
        standings = self.standings(extra)
        rows = next(g.rows for g in standings.groups if g.group_id == self.group)
        value = self._value(rows, standings)
        mine = next(r for r in rows if r.team == self.team).stats.points
        others = [r.stats.points for r in rows if r.team != self.team]
        sure_in = sum(p >= mine for p in others) < self.cut
        sure_out = sum(p > mine for p in others) >= self.cut + (1 if self.best_of_rest else 0)
        return value, sure_in, sure_out

    def _value(self, rows: Sequence[StandingRow], standings: Standings) -> float:
        value = _place_value(rows, self.team, self.cut)
        if value == 0 and self.best_of_rest and standings.rest:
            value = _place_value(standings.rest, self.team, self.best_of_rest)
        return value


def _place_value(rows: Sequence[StandingRow], team: str, places: int) -> float:
    row = next((r for r in rows if r.team == team), None)
    if row is None:
        return 0
    tied = sum(1 for r in rows if r.position == row.position)
    first, last = row.position, row.position + tied - 1
    if last <= places:
        return 1
    if first > places:
        return 0
    return 0.5


def _table(
    judge: _Judge,
    *,
    max_branches: int,
    samples: int,
    seed: bytes,
    weights: OutcomeWeights | None,
) -> _Table:
    fixtures = tuple(judge.relevant())
    options = tuple(
        tuple(judge.sport.hypothetical_outcomes(f, judge.state.rules, knockout=False))
        for f in fixtures
    )
    branches = 1
    for opts in options:
        branches *= len(opts)
    exact = branches <= max_branches
    if exact:
        choice_sets: Sequence[tuple[int, ...]] = list(
            itertools.product(*(range(len(o)) for o in options))
        )
    else:
        rng = DeterministicRng(seed)
        choice_sets = [
            tuple(_pick(rng, f, len(o), weights) for f, o in zip(fixtures, options, strict=True))
            for _ in range(samples)
        ]
    completions = []
    for choices in choice_sets:
        extra = [
            judge.result(f, opts[i]) for f, opts, i in zip(fixtures, options, choices, strict=True)
        ]
        completions.append(_Completion(choices, *judge.judge(extra)))
    return _Table(judge.team, fixtures, options, tuple(completions), exact)


def _pick(
    rng: DeterministicRng, fixture: Fixture, count: int, weights: OutcomeWeights | None
) -> int:
    if weights is None:
        return rng.randbelow(count)
    probabilities = list(weights(fixture))
    point = rng.randbelow(1_000_000) / 1_000_000 * sum(probabilities)
    for index, p in enumerate(probabilities):
        point -= p
        if point < 0:
            return index
    return count - 1


def _side(result: MatchResult, sport: SportModule) -> Side:
    key = sport.outcome_key(result, result.home)
    return "home" if key == "win" else "away" if key == "loss" else "draw"


def _condition(judge: _Judge, fixture: Fixture, outcome: SportResult, margin: int = 1) -> Condition:
    result = judge.result(fixture, outcome)
    side = _side(result, judge.sport)
    winner = result.home if side == "home" else result.away if side == "away" else None
    return Condition(fixture.match_id, side, winner, margin)


# --- thresholds ------------------------------------------------------------------------------


def _thresholds(judge: _Judge, table: _Table, completion: _Completion) -> list[Condition]:
    """Other matches whose winning margin flips the team's fate in this completion."""
    axis = judge.sport.margin_axis()
    base = [
        judge.result(f, opts[i])
        for f, opts, i in zip(table.fixtures, table.options, completion.choices, strict=True)
    ]
    found: list[Condition] = []
    for index, fixture in enumerate(table.fixtures):
        if judge.team in (fixture.home, fixture.away):
            continue
        side = _side(base[index], judge.sport)
        if side == "draw":
            continue
        for margin in range(2, axis.max_margin + 1):
            outcome = axis.make(margin, 0) if side == "home" else axis.make(0, margin)
            trial = [*base[:index], judge.result(fixture, outcome), *base[index + 1 :]]
            if judge.judge(trial)[0] != completion.value:
                found.append(_condition(judge, fixture, outcome, margin))
                break
    return found


# --- classification and paths ----------------------------------------------------------------


def _own_indices(table: _Table) -> list[int]:
    return [i for i, f in enumerate(table.fixtures) if table.team in (f.home, f.away)]


def _team_outcome(judge: _Judge, fixture: Fixture, outcome: SportResult) -> str:
    return judge.sport.outcome_key(judge.result(fixture, outcome), judge.team)


def _classify(judge: _Judge, table: _Table) -> Status:
    rows = table.completions
    if all(c.sure_in for c in rows):
        return "clinched"
    if all(c.sure_out for c in rows):
        return "eliminated"
    own = _own_indices(table)
    if not own:
        return "alive"

    def wins(c: _Completion, index: int) -> bool:
        fixture = table.fixtures[index]
        return _team_outcome(judge, fixture, table.options[index][c.choices[index]]) == "win"

    if all(c.sure_in for c in rows if all(wins(c, i) for i in own)):
        return "in_control"
    if all(c.sure_out for c in rows if not wins(c, own[0])):
        return "must_win"
    return "alive"


def _bounds_status(judge: _Judge) -> Status | None:
    """Clinched or eliminated from points bounds alone (when sampling)."""
    table = judge.standings(())
    rows = next(g.rows for g in table.groups if g.group_id == judge.group)
    points = judge.state.rules.points.table
    best, worst = max(points.values()), min(points.values())
    left: dict[str, int] = defaultdict(int)
    for fixture in judge.relevant():
        for team in (fixture.home, fixture.away):
            if team is not None:
                left[team] += 1
    now = {r.team: r.stats.points for r in rows}
    low = now[judge.team] + left[judge.team] * worst
    high = now[judge.team] + left[judge.team] * best
    others = [t for t in now if t != judge.team]
    if sum(now[t] + left[t] * best >= low for t in others) < judge.cut:
        return "clinched"
    extra = 1 if judge.best_of_rest else 0
    if sum(now[t] + left[t] * worst > high for t in others) >= judge.cut + extra:
        return "eliminated"
    return None


def _share(rows: Sequence[_Completion]) -> float:
    return sum(c.value for c in rows) / len(rows) if rows else 0.0


def _path(
    judge: _Judge,
    table: _Table,
    rows: Sequence[_Completion],
    own: int | None,
    outcome_index: int | None,
) -> ScenarioPath:
    names = {t.id: t.name for t in judge.state.teams}
    fixture = table.fixtures[own] if own is not None else None
    outcome = None
    if fixture is not None and own is not None and outcome_index is not None:
        outcome = _team_outcome(judge, fixture, table.options[own][outcome_index])

    unless: list[Condition] = []
    through_if: list[Condition] = []
    out_if: list[Condition] = []
    if all(c.sure_in for c in rows):
        result: PathResult = "through"
    elif all(c.sure_out for c in rows):
        result = "out"
    elif all(c.value == 1 for c in rows) or all(c.value == 0 for c in rows):
        result = "through" if rows[0].value == 1 else "out"
        flips: dict[tuple[str, str | None], Condition] = {}
        for completion in rows:
            if not (completion.sure_in or completion.sure_out):
                for found in _thresholds(judge, table, completion):
                    key = (found.match_id, found.winner)
                    if key not in flips or found.min_margin < flips[key].min_margin:
                        flips[key] = found
        unless = sorted(flips.values(), key=lambda c: (c.match_id, c.min_margin))
    else:
        result = "depends"
        for index, other in enumerate(table.fixtures):
            if judge.team in (other.home, other.away):
                continue
            for choice, option in enumerate(table.options[index]):
                subset = [c for c in rows if c.choices[index] == choice]
                share = _share(subset)
                if subset and share == 1:
                    through_if.append(_condition(judge, other, option))
                elif subset and share == 0:
                    out_if.append(_condition(judge, other, option))

    teams = {f.match_id: (f.home or "", f.away or "") for f in table.fixtures}

    def text(condition: Condition) -> str:
        return _describe(condition, names, teams[condition.match_id])

    summary = _summary(outcome, result, unless, through_if, out_if, text)
    return ScenarioPath(
        outcome=outcome,
        match_id=fixture.match_id if fixture is not None else None,
        result=result,
        share=_share(rows),
        unless=tuple(unless),
        through_if=tuple(through_if),
        out_if=tuple(out_if),
        summary=summary,
    )


def _describe(
    condition: Condition, names: Mapping[str, str], fixture_teams: tuple[str, str]
) -> str:
    home, away = (names.get(t, t) for t in fixture_teams)
    if condition.outcome == "draw":
        return f"{home} and {away} draw"
    winner, loser = (home, away) if condition.outcome == "home" else (away, home)
    margin = f" by {condition.min_margin} or more" if condition.min_margin > 1 else ""
    return f"{winner} beat {loser}{margin}"


def _summary(
    outcome: str | None,
    result: PathResult,
    unless: Sequence[Condition],
    through_if: Sequence[Condition],
    out_if: Sequence[Condition],
    text: Callable[[Condition], str],
) -> str:
    head = f"{outcome.capitalize()}: " if outcome else ""
    if result == "depends":
        parts = []
        if through_if:
            parts.append("through if " + " or ".join(text(c) for c in through_if[:2]))
        if out_if:
            parts.append("out if " + " or ".join(text(c) for c in out_if[:2]))
        return head + ("; ".join(parts) or "depends on other results") + "."
    tail = f" unless {' or '.join(text(c) for c in unless[:2])}" if unless else ""
    return f"{head}{result}{tail}."


def _paths(judge: _Judge, table: _Table) -> tuple[ScenarioPath, ...]:
    own = _own_indices(table)
    if not own:
        return (_path(judge, table, table.completions, None, None),)
    first = own[0]
    paths = []
    for choice in range(len(table.options[first])):
        rows = [c for c in table.completions if c.choices[first] == choice]
        if rows:
            paths.append(_path(judge, table, rows, first, choice))
    return tuple(paths[:MAX_PATHS])


# --- knockout --------------------------------------------------------------------------------


def _knockout(
    state: TournamentState,
    team: str,
    bracket: Bracket,
    knockout_results: Mapping[str, MatchResult],
) -> KnockoutPath | None:
    resolution = resolve_bracket(bracket, state, knockout_results=knockout_results)
    mine = [m for m in resolution.matches if team in (m.home.team, m.away.team)]
    if not mine:
        return None
    current = mine[-1]
    sport = get_sport(state.rules.sport)
    opponent_slot = current.away if current.home.team == team else current.home
    route = [current.code]
    while True:
        source = winner_source(route[-1])
        following = next(
            (m.code for m in bracket.matches if source in (m.home_source, m.away_source)), None
        )
        if following is None:
            break
        route.append(following)
    played = knockout_results.get(current.code)
    if played is not None:
        won = sport.knockout_winner(played) == team
        if not won or current.code == route[-1]:
            return KnockoutPath(
                next_match=None,
                opponent=None,
                opponent_could_be=(),
                route=(),
                eliminated_in=None if won else current.code,
            )
    return KnockoutPath(
        next_match=current.code,
        opponent=opponent_slot.team,
        opponent_could_be=opponent_slot.could_be,
        route=tuple(route),
        eliminated_in=None,
    )


# --- entry point -----------------------------------------------------------------------------


def compute_scenarios(
    state: TournamentState,
    team: str,
    *,
    bracket: Bracket | None = None,
    knockout_results: Mapping[str, MatchResult] | None = None,
    max_branches: int = MAX_BRANCHES,
    samples: int = SAMPLES,
    seed: bytes = b"scenarios",
    weights: OutcomeWeights | None = None,
) -> Scenario:
    """What `team` needs to go through (or its bracket path once it is in the knockout).

    `weights` gives outcome probabilities for sampling (uniform without it); exact
    enumeration ignores it, as every completion counts once.
    """
    if bracket is not None:
        path = _knockout(state, team, bracket, knockout_results or {})
        if path is not None:
            status: Status = "eliminated" if path.eliminated_in else "clinched"
            return Scenario(team, status, True, 0, 1.0 if status == "clinched" else 0.0, (), path)

    judge = _Judge(state, team)
    table = _table(judge, max_branches=max_branches, samples=samples, seed=seed, weights=weights)
    status = _classify(judge, table) if table.exact else _bounds_status(judge) or "alive"
    return Scenario(
        team=team,
        status=status,
        exact=table.exact,
        completions=len(table.completions),
        qualify_share=_share(table.completions),
        paths=_paths(judge, table),
    )


def outcome_table(
    state: TournamentState,
    team: str,
    *,
    max_branches: int = MAX_BRANCHES,
    samples: int = SAMPLES,
    seed: bytes = b"scenarios",
    weights: OutcomeWeights | None = None,
) -> tuple[
    tuple[Fixture, ...], tuple[tuple[Condition, ...], ...], list[tuple[tuple[int, ...], float]]
]:
    """For relevance: the fixtures that matter, each outcome as a condition, and every
    completion's choices with the team's value (1 through, 0 out, 0.5 when lots or the
    margins of other matches decide)."""
    judge = _Judge(state, team)
    table = _table(judge, max_branches=max_branches, samples=samples, seed=seed, weights=weights)
    conditions = tuple(
        tuple(_condition(judge, f, o) for o in opts)
        for f, opts in zip(table.fixtures, table.options, strict=True)
    )
    values = []
    for completion in table.completions:
        value = completion.value
        if completion.sure_in:
            value = 1.0
        elif completion.sure_out:
            value = 0.0
        elif _thresholds(judge, table, completion):
            value = 0.5  # the margins of other matches decide
        values.append((completion.choices, value))
    return table.fixtures, conditions, values
