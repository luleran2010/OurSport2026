"""Drawing lots: the engine never draws them; the organiser's recorded order decides a tie
that every other tiebreaker left open (docs/04-engine.md, Standings)."""

import dataclasses
import itertools

from hypothesis import given
from hypothesis import strategies as st

from engine.rules.config import Tiebreaker
from engine.standings import Standings, compute_standings
from engine.tests.test_standings import GD_FIRST, game, order, row, state

TEAMS = ("a", "b", "c")
# Every match 1-1: points, goal difference, goals and head-to-head cannot separate them.
LEVEL = [game(h, aw, 1, 1) for h, aw in itertools.combinations(TEAMS, 2)]


def level(lots: tuple[str, ...] = ()) -> Standings:
    base = state({"A": TEAMS}, LEVEL, tiebreakers=GD_FIRST)
    return compute_standings(dataclasses.replace(base, lots={"A": lots} if lots else {}))


def test_without_lots_the_tie_stays_open() -> None:
    standings = level()

    assert all(row(standings, t, "A").tied_unresolved for t in TEAMS)


def test_the_recorded_order_decides_the_tie() -> None:
    standings = level(("c", "a", "b"))

    assert order(standings) == ["c", "a", "b"]
    first = row(standings, "c")
    assert first.position == 1 and first.decided_by == Tiebreaker.DRAW_LOTS
    assert not first.tied_unresolved


def test_lots_missing_a_tied_team_decide_nothing() -> None:
    standings = level(("c", "a"))

    assert all(row(standings, t, "A").tied_unresolved for t in TEAMS)


def test_lots_never_override_a_decided_place() -> None:
    results = [game("a", "b", 3, 0), game("a", "c", 3, 0), game("b", "c", 1, 1)]
    base = state({"A": TEAMS}, results, tiebreakers=GD_FIRST)

    standings = compute_standings(dataclasses.replace(base, lots={"A": ("c", "b", "a")}))

    assert order(standings)[0] == "a"  # won both: the lots only order b and c
    assert order(standings)[1:] == ["c", "b"]


@given(st.permutations(TEAMS))
def test_any_drawn_order_is_kept(drawn: list[str]) -> None:
    assert order(level(tuple(drawn))) == drawn
