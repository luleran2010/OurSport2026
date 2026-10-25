"""Tournament simulation (docs/04-engine.md, Season simulation).

Every remaining group fixture is sampled from the prediction model; group tables rank by
points, goal difference and goals scored, then a seeded draw (a fast stand-in for the
head-to-head steps, which matter in few runs); the knockout is played out with Elo
expectations (no draws). Deterministic for the seed.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from engine.bracket import Bracket
from engine.model import TournamentState
from engine.predictions import MatchContext, predict_match
from engine.ratings import RatingInfo, expected
from engine.rng import DeterministicRng
from engine.sports.football import FootballResult

RUNS = 10_000
_SCALE = 1 << 32
_MARGINS = ((1, 0.55), (2, 0.30), (3, 0.15))


@dataclass(frozen=True)
class TeamChances:
    team: str
    qualify: float
    win_group: float
    reach: dict[str, float]  # knockout round -> chance to play in it
    win: float  # win the tournament


class _Uniform:
    """Uniform floats from the deterministic stream, buffered for speed."""

    def __init__(self, rng: DeterministicRng) -> None:
        self._rng = rng

    def __call__(self) -> float:
        return self._rng.randbelow(_SCALE) / _SCALE


def _margin(u: float) -> int:
    total = 0.0
    for margin, weight in _MARGINS:
        total += weight
        if u < total:
            return margin
    return _MARGINS[-1][0]


def _team_for(
    source: str,
    places: Mapping[str | None, list[str]],
    rest: list[str],
    winners: Mapping[str, str],
    losers: Mapping[str, str],
) -> str | None:
    """The team a knockout placeholder stands for in one simulated run."""
    kind, _, ref = source.partition(":")
    if kind == "group":
        letter, _, pos = ref.partition(":")
        order = places.get(letter, [])
        index = int(pos) - 1
        return order[index] if index < len(order) else None
    if kind == "best_rest":
        index = int(ref) - 1
        return rest[index] if index < len(rest) else None
    if kind == "winner":
        return winners.get(ref)
    if kind == "loser":
        return losers.get(ref)
    return None


def simulate(
    state: TournamentState,
    ratings: Mapping[str, RatingInfo],
    *,
    bracket: Bracket | None = None,
    runs: int = RUNS,
    seed: bytes = b"simulation",
) -> dict[str, TeamChances]:
    rules = state.rules
    points = rules.points.table
    win_pts, draw_pts, loss_pts = points.get("win", 3), points.get("draw", 1), points.get("loss", 0)
    advancement = rules.advancement
    groups = {g: list(teams) for g, teams in state.groups.items()}
    group_of = {t: g for g, teams in groups.items() for t in teams}

    def rating(team: str) -> RatingInfo:
        return ratings.get(team) or RatingInfo(team, 1500.0, 0)

    base: dict[str, list[int]] = {
        t: [0, 0, 0] for t in group_of
    }  # points, goal difference, goals for
    for r in state.results:
        o = r.outcome
        if r.group_id not in groups or not isinstance(o, FootballResult):
            continue
        for team, mine, theirs in (
            (r.home, o.home_goals, o.away_goals),
            (r.away, o.away_goals, o.home_goals),
        ):
            if team in base:
                pts = win_pts if mine > theirs else draw_pts if mine == theirs else loss_pts
                base[team][0] += pts
                base[team][1] += mine - theirs
                base[team][2] += mine
    fixtures = []
    for f in state.fixtures:
        if f.home in base and f.away in base and f.group_id in groups:
            p = predict_match(rating(f.home), rating(f.away), MatchContext())
            home_p, draw_p = p.point[0], p.point[1] or 0.0
            fixtures.append((f.home, f.away, home_p, home_p + draw_p))

    uniform = _Uniform(DeterministicRng(seed))
    qualify: dict[str, int] = defaultdict(int)
    first: dict[str, int] = defaultdict(int)
    reach: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    wins: dict[str, int] = defaultdict(int)
    knockout = list(bracket.matches) if bracket else []

    for _ in range(runs):
        table = {t: list(v) for t, v in base.items()}
        for home, away, home_cut, draw_cut in fixtures:
            u = uniform()
            loser_goals = 1 if uniform() < 0.35 else 0
            if u < home_cut:
                margin = _margin(uniform())
                hg, ag = loser_goals + margin, loser_goals
            elif u < draw_cut:
                hg = ag = loser_goals
            else:
                margin = _margin(uniform())
                hg, ag = loser_goals, loser_goals + margin
            for team, mine, theirs in ((home, hg, ag), (away, ag, hg)):
                row = table[team]
                row[0] += win_pts if mine > theirs else draw_pts if mine == theirs else loss_pts
                row[1] += mine - theirs
                row[2] += mine
        places: dict[str | None, list[str]] = {}
        for g, teams in groups.items():
            order = sorted(
                teams,
                key=lambda t: (table[t][0], table[t][1], table[t][2], uniform()),
                reverse=True,
            )
            places[g] = order
            first[order[0]] += 1
            for t in order[: advancement.per_group]:
                qualify[t] += 1
        rest: list[str] = []
        if advancement.best_of_rest:
            candidates = [
                o[advancement.per_group] for o in places.values() if len(o) > advancement.per_group
            ]
            rest = sorted(
                candidates,
                key=lambda t: (table[t][0], table[t][1], table[t][2], uniform()),
                reverse=True,
            )
            for t in rest[: advancement.best_of_rest]:
                qualify[t] += 1
        if not knockout:
            continue
        winners: dict[str, str] = {}
        losers: dict[str, str] = {}

        for m in knockout:
            first_team, second_team = (
                _team_for(m.home_source, places, rest, winners, losers),
                _team_for(m.away_source, places, rest, winners, losers),
            )
            if first_team is None or second_team is None:
                continue
            reach[first_team][m.round] += 1
            reach[second_team][m.round] += 1
            first_wins = uniform() < expected(rating(first_team).rating, rating(second_team).rating)
            pair = (first_team, second_team) if first_wins else (second_team, first_team)
            winners[m.code], losers[m.code] = pair
            if m.code == "F":
                wins[winners[m.code]] += 1

    return {
        t: TeamChances(
            team=t,
            qualify=qualify[t] / runs,
            win_group=first[t] / runs,
            reach={r: c / runs for r, c in reach[t].items()},
            win=wins[t] / runs,
        )
        for t in group_of
    }
