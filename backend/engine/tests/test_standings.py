from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from engine.model import MatchResult, TeamRef, TournamentState
from engine.rules.config import AdvancementRule, PointsRule, RuleConfig, Tiebreaker
from engine.rules.format import FormatSpec
from engine.rules.presets import TIEBREAKER_PRESETS
from engine.sports.football import Cards, FootballResult
from engine.standings import GroupStandings, Standings, compute_standings
from engine.tests.conftest import make_rules

GD_FIRST = list(TIEBREAKER_PRESETS["football_gd_first"])
H2H_FIRST = list(TIEBREAKER_PRESETS["football_h2h_first"])


def game(
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
    *,
    group: str = "A",
    at: str = "",
    **kwargs: Any,
) -> MatchResult:
    return MatchResult(
        match_id=f"{group}:{home}-{away}:{at}",
        group_id=group,
        home=home,
        away=away,
        outcome=FootballResult(home_goals, away_goals, **kwargs),
        starts_at=at,
    )


def state(
    groups: Mapping[str, Sequence[str]],
    results: Sequence[MatchResult],
    *,
    rules: RuleConfig | None = None,
    **rule_overrides: Any,
) -> TournamentState:
    teams = sorted({t for members in groups.values() for t in members})
    rules = rules or make_rules(format="round_robin", **rule_overrides)
    return TournamentState(
        teams=tuple(TeamRef(t, t.upper()) for t in teams),
        groups={g: tuple(members) for g, members in groups.items()},
        results=tuple(results),
        fixtures=(),
        rules=rules,
        format=FormatSpec(team_count=len(teams), group_sizes=[len(m) for m in groups.values()]),
    )


def group(standings: Standings, group_id: str = "A") -> GroupStandings:
    return next(g for g in standings.groups if g.group_id == group_id)


def order(standings: Standings, group_id: str = "A") -> list[str]:
    return [row.team for row in group(standings, group_id).rows]


def row(standings: Standings, team: str, group_id: str = "A") -> Any:
    return next(r for r in group(standings, group_id).rows if r.team == team)


# --- no ties ---------------------------------------------------------------------------------


def test_points_alone_order_the_table() -> None:
    result = compute_standings(
        state(
            {"A": ["a", "b", "c"]},
            [game("a", "b", 2, 0), game("b", "c", 1, 0), game("a", "c", 1, 1)],
        )
    )

    assert order(result) == ["a", "b", "c"]
    assert [r.position for r in group(result).rows] == [1, 2, 3]
    assert row(result, "a").stats.points == 4
    assert row(result, "a").decided_by is Tiebreaker.POINTS
    assert not any(r.tied_unresolved for r in group(result).rows)


def test_knockout_results_do_not_count_in_the_group() -> None:
    knockout = MatchResult("ko", None, "c", "a", FootballResult(5, 0))

    result = compute_standings(state({"A": ["a", "c"]}, [game("a", "c", 1, 0), knockout]))

    assert row(result, "a").stats.played == 1


# --- two-way ties ----------------------------------------------------------------------------


# a and b both finish on 6 points; a won their meeting, b has the better goal difference.
TWO_WAY_TIED = [
    game("a", "b", 1, 0),  # a beats b
    game("b", "c", 5, 0),  # b big win
    game("a", "c", 0, 1),  # a loses to c
    game("a", "d", 1, 0),
    game("b", "d", 1, 0),
    game("c", "d", 0, 0),
]


def test_two_way_tie_goal_difference_first() -> None:
    # a: 6 pts, GF 2 GA 1 (+1); b: 6 pts, GF 6 GA 1 (+5)
    result = compute_standings(
        state({"A": ["a", "b", "c", "d"]}, TWO_WAY_TIED, tiebreakers=GD_FIRST)
    )

    assert order(result)[:2] == ["b", "a"]
    assert row(result, "b").decided_by is Tiebreaker.SCORE_DIFF
    assert row(result, "b").tiebreak_value == 5


def test_two_way_tie_head_to_head_first() -> None:
    result = compute_standings(
        state({"A": ["a", "b", "c", "d"]}, TWO_WAY_TIED, tiebreakers=H2H_FIRST)
    )

    assert order(result)[:2] == ["a", "b"]
    assert row(result, "a").decided_by is Tiebreaker.HEAD_TO_HEAD_POINTS
    assert row(result, "a").tiebreak_value == 3


# --- three-way ties --------------------------------------------------------------------------

# A cycle: everyone beat one rival, so head-to-head points are level; margins decide.
CYCLE = [game("a", "b", 3, 0), game("b", "c", 1, 0), game("c", "a", 1, 0)]


def test_three_way_cycle_split_by_head_to_head_goal_difference() -> None:
    # Mini-table: a +3-1 = +2, c +1-1 = 0, b -3+1 = -2
    result = compute_standings(state({"A": ["a", "b", "c"]}, CYCLE, tiebreakers=H2H_FIRST))

    assert order(result) == ["a", "c", "b"]
    assert {r.decided_by for r in group(result).rows} == {Tiebreaker.HEAD_TO_HEAD_DIFF}


# A, B, C level on points and on the three-team mini-table except A's goals; B beat C.
# Overall, C has the better goal difference thanks to a big win over D.
REAPPLY = [
    game("a", "b", 2, 1),
    game("c", "a", 2, 1),
    game("b", "c", 1, 0),
    game("a", "d", 1, 0),
    game("b", "d", 1, 0),
    game("c", "d", 3, 0),
]


def test_three_way_tie_reapplies_head_to_head_to_the_remaining_two() -> None:
    result = compute_standings(state({"A": ["a", "b", "c", "d"]}, REAPPLY, tiebreakers=H2H_FIRST))

    assert order(result) == ["a", "b", "c", "d"]
    assert row(result, "a").decided_by is Tiebreaker.HEAD_TO_HEAD_FOR
    assert row(result, "b").decided_by is Tiebreaker.HEAD_TO_HEAD_POINTS


def test_without_reapply_the_next_criterion_decides() -> None:
    result = compute_standings(
        state(
            {"A": ["a", "b", "c", "d"]},
            REAPPLY,
            tiebreakers=H2H_FIRST,
            head_to_head_reapply=False,
        )
    )

    assert order(result) == ["a", "c", "b", "d"]
    assert row(result, "c").decided_by is Tiebreaker.SCORE_DIFF


def test_three_way_tie_goal_difference_first_then_head_to_head() -> None:
    # a, b, c: 6 points, GD +2, 4 goals each; only their mini-table differs:
    # a +1 (beat b 2-0, lost to c 0-1), c 0, b -1.
    results = [
        game("a", "b", 2, 0),
        game("b", "c", 1, 0),
        game("c", "a", 1, 0),
        game("a", "d", 2, 1),
        game("b", "d", 3, 0),
        game("c", "d", 3, 1),
    ]

    result = compute_standings(state({"A": ["a", "b", "c", "d"]}, results, tiebreakers=GD_FIRST))

    assert order(result) == ["a", "c", "b", "d"]
    assert {row(result, t).stats.score_diff for t in "abc"} == {2}
    assert {row(result, t).decided_by for t in "abc"} == {Tiebreaker.HEAD_TO_HEAD_DIFF}


# --- four-way ties and unresolved ties -------------------------------------------------------


def test_four_way_all_draws_stays_unresolved_with_shared_position() -> None:
    teams = ["a", "b", "c", "d"]
    results = [game(h, a, 1, 1) for i, h in enumerate(teams) for a in teams[i + 1 :]]

    result = compute_standings(state({"A": teams}, results, tiebreakers=H2H_FIRST))

    rows = group(result).rows
    assert [r.position for r in rows] == [1, 1, 1, 1]
    assert all(r.tied_unresolved for r in rows)
    assert all(r.decided_by is None for r in rows)
    assert [r.team for r in rows] == teams  # listed by id, never an invented order


def test_two_teams_unresolved_below_a_clear_leader() -> None:
    results = [game("a", "b", 2, 0), game("a", "c", 2, 0), game("b", "c", 0, 0)]

    result = compute_standings(state({"A": ["a", "b", "c"]}, results, tiebreakers=GD_FIRST))

    assert [(r.team, r.position, r.tied_unresolved) for r in group(result).rows] == [
        ("a", 1, False),
        ("b", 2, True),
        ("c", 2, True),
    ]


def test_fair_play_breaks_a_tie() -> None:
    results = [
        game("a", "b", 1, 1, home_cards=Cards(yellow=1), away_cards=Cards(yellow=3)),
    ]

    result = compute_standings(state({"A": ["a", "b"]}, results, tiebreakers=GD_FIRST))

    assert order(result) == ["a", "b"]
    assert row(result, "a").decided_by is Tiebreaker.FAIR_PLAY
    assert row(result, "a").tiebreak_value == -1


# --- form, visibility, best of the rest ------------------------------------------------------


def test_form_is_the_last_five_in_playing_order() -> None:
    opponents = ["b", "c", "d", "e", "f", "g"]
    scores = [(1, 0), (0, 0), (0, 1), (2, 0), (3, 3), (0, 2)]
    results = [
        game("a", opp, h, a, at=f"2026-06-1{i}T10:00:00Z")
        for i, (opp, (h, a)) in enumerate(zip(opponents, scores, strict=True))
    ]

    result = compute_standings(state({"A": ["a", *opponents]}, list(reversed(results))))

    assert row(result, "a").form == ("D", "L", "W", "D", "L")


def test_standings_visible_passes_through() -> None:
    hidden = compute_standings(state({"A": ["a", "b"]}, [], standings_visible=False))

    assert hidden.visible is False


def test_best_third_placed_teams_ranked_across_groups() -> None:
    rules = make_rules(
        advancement=AdvancementRule(
            per_group=2,
            best_of_rest=1,
            rest_ranking=[Tiebreaker.POINTS_PER_GAME, Tiebreaker.SCORE_DIFF, Tiebreaker.DRAW_LOTS],
        )
    )
    groups = {"A": ["a1", "a2", "a3", "a4"], "B": ["b1", "b2", "b3"]}
    results = [
        # group A: a3 finishes third with 3 points from 3 games (1.0 per game)
        game("a1", "a2", 1, 0), game("a1", "a3", 1, 0), game("a1", "a4", 1, 0),
        game("a2", "a3", 1, 0), game("a2", "a4", 1, 0), game("a3", "a4", 1, 0),
        # group B: b3 finishes third with 1 point from 2 games (0.5 per game)
        game("b1", "b2", 1, 0, group="B"), game("b1", "b3", 1, 1, group="B"),
        game("b2", "b3", 1, 0, group="B"),
    ]  # fmt: skip

    result = compute_standings(state(groups, results, rules=rules))

    assert [r.team for r in result.rest] == ["a3", "b3"]
    assert result.rest[0].decided_by is Tiebreaker.POINTS_PER_GAME


# --- properties ------------------------------------------------------------------------------

TEAMS = ["a", "b", "c", "d"]
PAIRS = [(h, a) for i, h in enumerate(TEAMS) for a in TEAMS[i + 1 :]]
scores = st.integers(min_value=0, max_value=4)
group_results = st.lists(st.tuples(scores, scores), min_size=len(PAIRS), max_size=len(PAIRS)).map(
    lambda goals: [game(h, a, hg, ag) for (h, a), (hg, ag) in zip(PAIRS, goals, strict=True)]
)


@given(group_results, st.randoms(), st.sampled_from([GD_FIRST, H2H_FIRST]))
def test_standings_do_not_depend_on_result_order(
    results: list[MatchResult], rnd: Any, tiebreakers: list[Tiebreaker]
) -> None:
    shuffled = list(results)
    rnd.shuffle(shuffled)

    first = compute_standings(state({"A": TEAMS}, results, tiebreakers=tiebreakers))
    second = compute_standings(state({"A": TEAMS}, shuffled, tiebreakers=tiebreakers))

    assert first == second


@given(group_results)
def test_total_points_equal_points_awarded_per_match(results: list[MatchResult]) -> None:
    rules = make_rules(format="round_robin")
    table = rules.points.table

    standings = compute_standings(state({"A": TEAMS}, results, rules=rules))

    def awarded(r: MatchResult) -> int:
        outcome = r.outcome
        assert isinstance(outcome, FootballResult)
        if outcome.home_goals == outcome.away_goals:
            return 2 * table["draw"]
        return table["win"] + table["loss"]

    assert sum(r.stats.points for r in group(standings).rows) == sum(awarded(r) for r in results)


@given(group_results, st.sampled_from([GD_FIRST, H2H_FIRST]))
def test_table_invariants(results: list[MatchResult], tiebreakers: list[Tiebreaker]) -> None:
    rows = group(compute_standings(state({"A": TEAMS}, results, tiebreakers=tiebreakers))).rows

    assert rows[0].position == 1
    assert sorted(r.team for r in rows) == TEAMS
    for above, below in pairwise(rows):
        assert above.stats.points >= below.stats.points
        assert above.position <= below.position
        if above.position == below.position:
            assert above.tied_unresolved and below.tied_unresolved
            assert above.stats.points == below.stats.points
            assert above.stats.score_diff == below.stats.score_diff


@given(group_results)
def test_adding_a_win_never_lowers_points(results: list[MatchResult]) -> None:
    before = compute_standings(state({"A": TEAMS}, results))
    extra = game("a", "b", 1, 0, at="2026-12-31T00:00:00Z")
    after = compute_standings(state({"A": TEAMS}, [*results, extra]))

    assert row(after, "a").stats.points == row(before, "a").stats.points + 3


def test_points_rule_changes_flow_through() -> None:
    rules = make_rules(
        format="round_robin", points=PointsRule(table={"win": 2, "draw": 1, "loss": 0})
    )

    result = compute_standings(state({"A": ["a", "b"]}, [game("a", "b", 1, 0)], rules=rules))

    assert row(result, "a").stats.points == 2
