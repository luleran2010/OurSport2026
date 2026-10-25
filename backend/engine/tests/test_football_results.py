from collections.abc import Callable, Sequence
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from engine.model import Fixture, MatchResult, TeamStats
from engine.rules.config import RuleConfig, Tiebreaker
from engine.sports.football import FOOTBALL, Cards, FootballResult
from engine.tests.conftest import make_rules

HOME, AWAY = "home-fc", "away-fc"


def match(
    result: FootballResult, *, home: str = HOME, away: str = AWAY, walkover: bool = False
) -> MatchResult:
    return MatchResult(
        match_id=f"{home}-{away}-{result.home_goals}-{result.away_goals}",
        group_id="A",
        home=home,
        away=away,
        outcome=result,
        walkover=walkover,
    )


def stats(results: Sequence[MatchResult], team: str, rules: RuleConfig | None = None) -> TeamStats:
    return FOOTBALL.team_stats(results, team, rules or make_rules())


# --- results and outcomes --------------------------------------------------------------------


def test_regulation_result_outcomes() -> None:
    win = match(FootballResult(2, 1))

    assert FOOTBALL.outcome_key(win, HOME) == "win"
    assert FOOTBALL.outcome_key(win, AWAY) == "loss"
    assert FOOTBALL.outcome_key(match(FootballResult(1, 1)), HOME) == "draw"


def test_extra_time_winner_counts_as_a_win() -> None:
    result = match(FootballResult(3, 2, decided_by="extra_time"))

    assert FOOTBALL.outcome_key(result, HOME) == "win"
    assert FOOTBALL.knockout_winner(result) == HOME


def test_penalty_shootout_is_a_draw_for_points_but_decides_the_knockout() -> None:
    shootout = match(
        FootballResult(1, 1, decided_by="penalties", home_penalties=3, away_penalties=4)
    )

    assert FOOTBALL.outcome_key(shootout, HOME) == "draw"
    assert FOOTBALL.outcome_key(shootout, AWAY) == "draw"
    assert FOOTBALL.knockout_winner(shootout) == AWAY


def test_knockout_needs_a_winner() -> None:
    with pytest.raises(ValueError, match="no winner"):
        FOOTBALL.knockout_winner(match(FootballResult(0, 0)))


def test_outcome_for_a_team_not_in_the_match_is_an_error() -> None:
    with pytest.raises(ValueError, match="not in match"):
        FOOTBALL.outcome_key(match(FootballResult(1, 0)), "someone-else")


SHOOTOUT: Final = "penalties"


@pytest.mark.parametrize(
    ("make", "message"),
    [
        pytest.param(lambda: FootballResult(-1, 0), "negative", id="negative"),
        pytest.param(
            lambda: FootballResult(1, 1, home_penalties=4, away_penalties=3),
            "shootout",
            id="penalties-without-shootout",
        ),
        pytest.param(
            lambda: FootballResult(2, 1, SHOOTOUT, home_penalties=4, away_penalties=3),
            "level",
            id="shootout-after-a-winner",
        ),
        pytest.param(
            lambda: FootballResult(1, 1, SHOOTOUT, home_penalties=4, away_penalties=4),
            "winner",
            id="shootout-level",
        ),
        pytest.param(
            lambda: FootballResult(1, 1, SHOOTOUT), "shootout score", id="shootout-missing-score"
        ),
        pytest.param(lambda: FootballResult(1, 1, "extra_time"), "level", id="extra-time-level"),
    ],
)
def test_inconsistent_results_are_rejected(make: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make()


# --- walkovers -------------------------------------------------------------------------------


def test_walkover_default_is_three_nil() -> None:
    result = FOOTBALL.walkover_result(make_rules(), winner="away")

    assert (result.home_goals, result.away_goals) == (0, 3)


def test_walkover_uses_the_configured_score() -> None:
    rules = make_rules(walkover={"score_for": 5, "score_against": 0})
    walkover = match(FOOTBALL.walkover_result(rules, winner="home"), walkover=True)

    home = stats([walkover], HOME, rules)

    assert (home.score_for, home.score_against, home.points, home.won) == (5, 0, 3, 1)
    assert stats([walkover], AWAY, rules).points == 0


# --- team stats ------------------------------------------------------------------------------


def test_team_stats_add_up_across_home_and_away_matches() -> None:
    results = [
        match(FootballResult(2, 0)),  # home win
        match(FootballResult(1, 1), home="third", away=HOME),  # away draw
        match(FootballResult(3, 1), home="fourth", away=HOME),  # away loss
        match(FootballResult(0, 0), home="third", away="fourth"),  # not ours
    ]

    home = stats(results, HOME)

    assert (home.played, home.won, home.drawn, home.lost) == (3, 1, 1, 1)
    assert (home.score_for, home.score_against, home.score_diff) == (4, 4, 0)
    assert home.away_score_for == 2
    assert home.points == 4
    assert home.outcome_counts == {"win": 1, "draw": 1, "loss": 1}


def test_points_follow_the_rule_table() -> None:
    rules = make_rules(
        points=make_rules().points.model_copy(update={"table": {"win": 2, "draw": 1, "loss": 0}})
    )

    assert stats([match(FootballResult(1, 0))], HOME, rules).points == 2


def test_fair_play_points_use_the_rule_weights() -> None:
    result = FootballResult(
        1, 0, home_cards=Cards(yellow=2, second_yellow=1, red=1), away_cards=Cards(yellow=1)
    )
    custom = make_rules(fair_play_points={"yellow": 1, "second_yellow": 2, "red": 5})

    assert stats([match(result)], HOME).fair_play_points == 2 * 1 + 3 + 3
    assert stats([match(result)], AWAY).fair_play_points == 1
    assert stats([match(result)], HOME, custom).fair_play_points == 2 + 2 + 5


def test_team_without_matches_has_empty_stats() -> None:
    empty = stats([], HOME)

    assert (empty.played, empty.points, empty.score_diff) == (0, 0, 0)


scores = st.integers(min_value=0, max_value=9)


@given(st.lists(st.tuples(scores, scores, st.booleans()), max_size=12))
def test_points_equal_the_sum_over_matches(games: list[tuple[int, int, bool]]) -> None:
    rules = make_rules()
    results = [
        match(
            FootballResult(h, a),
            home=HOME if at_home else f"opp{i}",
            away=f"opp{i}" if at_home else HOME,
        )
        for i, (h, a, at_home) in enumerate(games)
    ]

    total = stats(results, HOME, rules)

    expected = sum(rules.points.table[FOOTBALL.outcome_key(r, HOME)] for r in results)
    assert total.points == expected
    assert total.played == len(results)
    assert total.won + total.drawn + total.lost == total.played
    assert total.score_diff == total.score_for - total.score_against


@given(st.lists(st.tuples(scores, scores), max_size=8), st.randoms())
def test_stats_do_not_depend_on_result_order(games: list[tuple[int, int]], rnd: object) -> None:
    results = [match(FootballResult(h, a), away=f"opp{i}") for i, (h, a) in enumerate(games)]
    shuffled = list(results)
    rnd.shuffle(shuffled)  # type: ignore[attr-defined]  # Hypothesis' Random proxy lacks shuffle in its stubs

    assert stats(results, HOME) == stats(shuffled, HOME)


# --- metrics, hypotheticals, margins ---------------------------------------------------------


def test_metrics_rank_higher_values_higher() -> None:
    result = FootballResult(3, 1, home_cards=Cards(yellow=2))
    home = stats([match(result), match(FootballResult(0, 0), away="x")], HOME)

    assert FOOTBALL.metric(Tiebreaker.POINTS, home) == 4
    assert FOOTBALL.metric(Tiebreaker.POINTS_PER_GAME, home) == 2.0
    assert FOOTBALL.metric(Tiebreaker.SCORE_DIFF, home) == 2
    assert FOOTBALL.metric(Tiebreaker.SCORE_FOR, home) == 3
    assert FOOTBALL.metric(Tiebreaker.WINS, home) == 1
    assert FOOTBALL.metric(Tiebreaker.FAIR_PLAY, home) == -2  # fewer points is better
    assert FOOTBALL.metric(Tiebreaker.HEAD_TO_HEAD_POINTS, home) is None  # mini-table
    assert FOOTBALL.metric(Tiebreaker.DRAW_LOTS, home) is None


def test_points_per_game_without_games_is_zero() -> None:
    assert FOOTBALL.metric(Tiebreaker.POINTS_PER_GAME, stats([], HOME)) == 0.0


FIXTURE = Fixture(
    match_id="m1", group_id="A", home=HOME, away=AWAY, starts_at="2026-06-12T10:00:00Z"
)


def test_group_hypotheticals_cover_win_draw_loss() -> None:
    outcomes = FOOTBALL.hypothetical_outcomes(FIXTURE, make_rules(), knockout=False)

    keys = {FOOTBALL.outcome_key(match(o), HOME) for o in outcomes}
    assert keys == {"win", "draw", "loss"}


def test_knockout_hypotheticals_always_have_a_winner() -> None:
    outcomes = FOOTBALL.hypothetical_outcomes(FIXTURE, make_rules(), knockout=True)

    assert {FOOTBALL.knockout_winner(match(o)) for o in outcomes} == {HOME, AWAY}


def test_margin_axis_builds_results_by_goal_difference() -> None:
    axis = FOOTBALL.margin_axis()

    assert axis.unit == "goal_difference"
    assert axis.max_margin == 10
    result = axis.make(3, 1)
    assert isinstance(result, FootballResult)
    assert (result.home_goals, result.away_goals) == (3, 1)
