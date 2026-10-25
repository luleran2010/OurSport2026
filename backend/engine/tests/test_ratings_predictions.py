from hypothesis import given, settings
from hypothesis import strategies as st

from engine.predictions import MatchContext, placement_label, predict_match
from engine.ratings import RatingInfo, carry_over, expected, prior, update


def test_seeding_prior_and_carry_over() -> None:
    assert prior("a", pot=1).rating == 1575
    assert prior("b", pot=4).rating == 1425
    assert prior("c").prior_source == "default"
    strong = RatingInfo("a", 1700, 20)
    assert carry_over(strong, junior=False).rating == 1650
    assert carry_over(strong, junior=True).rating == 1600


def test_winner_gains_what_the_loser_loses_and_bigger_wins_count_more() -> None:
    home, away = RatingInfo("h", 1500, 0), RatingInfo("a", 1500, 0)

    h1, a1 = update(home, away, 1, 0)
    h3, _ = update(home, away, 3, 0)
    hp, ap = update(home, away, 1, 1, penalties=True)

    assert h1.rating > 1500 > a1.rating
    assert round(h1.rating - 1500, 6) == round(1500 - a1.rating, 6)
    assert h3.rating > h1.rating
    assert (hp.rating, ap.rating) == (1500, 1500)  # a shootout counts as a draw
    assert h1.games == 1


def test_no_home_advantage_at_a_single_venue() -> None:
    assert expected(1500, 1500) == 0.5
    assert expected(1500, 1500, home_advantage=40) > 0.5


def test_confidence_is_none_below_three_games_and_factors_carry_the_seeding() -> None:
    home, away = RatingInfo("h", 1525, 2, "seeding"), RatingInfo("a", 1475, 7)
    ctx = MatchContext(seeding={"home": placement_label(2, 2025) or ""})

    prediction = predict_match(home, away, ctx)

    assert prediction.confidence == "none"
    assert prediction.factors[0].text == "2025 runner-up"
    assert (
        predict_match(
            RatingInfo("h", 1500, 12), RatingInfo("a", 1500, 15), MatchContext()
        ).confidence
        == "high"
    )


def test_knockout_has_no_draw() -> None:
    p = predict_match(
        RatingInfo("h", 1600, 5), RatingInfo("a", 1500, 5), MatchContext(knockout=True)
    )

    assert p.draw is None
    assert abs(p.point[0] + p.point[2] - 1) < 1e-3


@settings(max_examples=200, deadline=None)
@given(
    st.floats(1200, 1800),
    st.floats(1200, 1800),
    st.integers(0, 30),
    st.integers(0, 30),
    st.booleans(),
)
def test_property_ranges_contain_the_point_and_chances_sum_to_one(
    home_r: float, away_r: float, home_g: int, away_g: int, knockout: bool
) -> None:
    p = predict_match(
        RatingInfo("h", home_r, home_g),
        RatingInfo("a", away_r, away_g),
        MatchContext(knockout=knockout),
    )

    assert p.home_win[0] <= p.point[0] <= p.home_win[1]
    assert p.away_win[0] <= p.point[2] <= p.away_win[1]
    if p.draw is not None and p.point[1] is not None:
        assert p.draw[0] <= p.point[1] <= p.draw[1]
    assert abs(sum(x for x in p.point if x is not None) - 1) < 1e-3


def test_backtest_beats_guessing() -> None:
    from engine.tests.backtest import run

    brier, baseline = run()

    assert brier < baseline
