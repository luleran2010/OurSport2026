import pytest
from hypothesis import given
from hypothesis import strategies as st

from engine.rules.config import AdvancementRule, Tiebreaker
from engine.rules.format import (
    FormatSpec,
    KnockoutSpec,
    best_rest_source,
    group_match_count,
    group_source,
    groups_then_knockout,
    knockout_match_codes,
    knockout_only,
    league,
    qualifier_sources,
    total_match_count,
)
from engine.rules.validate import validate_format
from engine.tests.conftest import make_rules

BEST_THIRDS = AdvancementRule(
    per_group=2,
    best_of_rest=4,
    rest_ranking=[Tiebreaker.POINTS, Tiebreaker.SCORE_DIFF, Tiebreaker.DRAW_LOTS],
)


def test_sixteen_teams_in_four_groups_play_thirty_two_matches() -> None:
    choice = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)

    assert choice.format.knockout is not None
    assert choice.format.knockout.rounds == ["quarter_final", "semi_final", "final"]
    assert group_match_count(choice.format) == 24
    assert knockout_match_codes(choice.format) == [
        "QF1", "QF2", "QF3", "QF4", "SF1", "SF2", "3P", "F",
    ]  # fmt: skip
    assert total_match_count(choice.format) == 32


def test_qualifier_sources_use_the_placeholder_grammar() -> None:
    choice = groups_then_knockout([4] * 6, per_group=2, best_of_rest=4)

    sources = qualifier_sources(choice.format, choice.advancement)

    assert sources[:3] == ["group:A:1", "group:A:2", "group:B:1"]
    assert sources[-4:] == [best_rest_source(r) for r in (1, 2, 3, 4)]
    assert len(sources) == 16
    assert group_source("C", 2) == "group:C:2"


def test_double_round_robin_league() -> None:
    choice = league(6, double=True)

    assert choice.format.group_rounds == 2
    assert total_match_count(choice.format) == 30
    assert validate_format(choice.format, make_rules(format="double_round_robin")) == []


def test_knockout_only_needs_a_power_of_two() -> None:
    assert knockout_only(8).format.knockout is not None
    with pytest.raises(ValueError, match="byes are not supported"):
        knockout_only(12)


def test_builder_rejects_brackets_it_cannot_fill() -> None:
    with pytest.raises(ValueError, match="6 qualifiers"):
        groups_then_knockout([4, 4, 4], per_group=2)


@given(
    group_count=st.integers(min_value=1, max_value=8),
    size=st.integers(min_value=3, max_value=6),
    per_group=st.integers(min_value=1, max_value=2),
    best_of_rest=st.integers(min_value=0, max_value=8),
)
def test_built_formats_validate_and_fill_their_bracket(
    group_count: int, size: int, per_group: int, best_of_rest: int
) -> None:
    qualifiers = group_count * per_group + best_of_rest
    try:
        choice = groups_then_knockout(
            [size] * group_count, per_group=per_group, best_of_rest=best_of_rest
        )
    except ValueError:
        assert qualifiers not in (2, 4, 8, 16) or best_of_rest > group_count
        return

    rules = make_rules(
        advancement=choice.advancement.model_copy(
            update={
                "rest_ranking": [Tiebreaker.POINTS, Tiebreaker.DRAW_LOTS] if best_of_rest else []
            }
        )
    )
    assert validate_format(choice.format, rules) == []
    assert len(qualifier_sources(choice.format, choice.advancement)) == qualifiers


def _codes(fmt: FormatSpec, advancement: AdvancementRule, **rule_overrides: object) -> list[str]:
    rules = make_rules(advancement=advancement, **rule_overrides)
    return [issue.code for issue in validate_format(fmt, rules)]


def test_advancement_must_fill_the_bracket_exactly() -> None:
    fmt = FormatSpec(
        team_count=16,
        group_sizes=[4, 4, 4, 4],
        knockout=KnockoutSpec(rounds=["semi_final", "final"]),
    )

    issues = validate_format(fmt, make_rules())

    assert [i.code for i in issues] == ["advancement_bracket_mismatch"]
    assert issues[0].message == (
        "4 groups x top 2 = 8 qualifiers, but a bracket starting at the semi final takes 4"
    )


def test_advancement_larger_than_group_is_rejected() -> None:
    fmt = FormatSpec(
        team_count=9,
        group_sizes=[3, 3, 3],
        knockout=KnockoutSpec(rounds=["quarter_final", "semi_final", "final"]),
    )

    codes = _codes(fmt, AdvancementRule(per_group=4))

    assert "advancement_exceeds_group" in codes


def test_team_count_must_match_group_sizes() -> None:
    fmt = FormatSpec(
        team_count=15,
        group_sizes=[4, 4, 4, 4],
        knockout=KnockoutSpec(rounds=["quarter_final", "semi_final", "final"]),
    )

    assert _codes(fmt, AdvancementRule(per_group=2)) == ["team_count_mismatch"]


def test_more_best_of_rest_than_groups_is_rejected() -> None:
    fmt = FormatSpec(
        team_count=8,
        group_sizes=[4, 4],
        knockout=KnockoutSpec(rounds=["semi_final", "final"]),
    )
    advancement = AdvancementRule(
        per_group=1, best_of_rest=3, rest_ranking=[Tiebreaker.POINTS, Tiebreaker.DRAW_LOTS]
    )

    assert "best_of_rest_too_many" in _codes(fmt, advancement)


def test_unequal_groups_need_points_per_game_for_cross_group_ranking() -> None:
    fmt = FormatSpec(
        team_count=11,
        group_sizes=[4, 4, 3],
        knockout=KnockoutSpec(rounds=["quarter_final", "semi_final", "final"]),
    )
    advancement = AdvancementRule(
        per_group=2, best_of_rest=2, rest_ranking=[Tiebreaker.POINTS, Tiebreaker.DRAW_LOTS]
    )

    assert _codes(fmt, advancement) == ["rest_ranking_unequal_groups"]


def test_knockout_rounds_must_be_consecutive_and_end_with_the_final() -> None:
    fmt = FormatSpec(
        team_count=16,
        group_sizes=[4, 4, 4, 4],
        knockout=KnockoutSpec(rounds=["quarter_final", "final"]),
    )

    assert "knockout_rounds_invalid" in _codes(fmt, AdvancementRule(per_group=2))


def test_third_place_match_needs_semi_finals() -> None:
    fmt = FormatSpec(
        team_count=4,
        group_sizes=[2, 2],
        knockout=KnockoutSpec(rounds=["final"], third_place_match=True),
    )

    assert "third_place_needs_semi_final" in _codes(fmt, AdvancementRule(per_group=1))


def test_competition_format_must_agree_with_the_format_spec() -> None:
    choice = groups_then_knockout([4, 4], per_group=2)

    codes = _codes(choice.format, choice.advancement, format="round_robin")

    assert codes == ["format_mismatch"]


def test_knockout_without_a_way_to_decide_draws_is_rejected() -> None:
    choice = groups_then_knockout([4, 4], per_group=2)
    match = {"periods": 2, "period_minutes": 20, "penalties_in_knockout": False}

    assert _codes(choice.format, choice.advancement, match=match) == ["knockout_draws_undecided"]


def test_extra_time_in_knockout_must_be_configured_in_match_rules() -> None:
    choice = groups_then_knockout(
        [4, 4], per_group=2, final_draws_decided_by="extra_time_then_penalties"
    )

    assert _codes(choice.format, choice.advancement) == ["extra_time_not_configured"]


def test_custom_pairs_must_use_every_qualifier_once() -> None:
    fmt = FormatSpec(
        team_count=8,
        group_sizes=[4, 4],
        knockout=KnockoutSpec(
            rounds=["semi_final", "final"],
            crossover="custom",
            custom_pairs=[("group:A:1", "group:B:2"), ("group:A:1", "group:Z:9")],
        ),
    )

    issues = validate_format(fmt, make_rules())

    assert [i.code for i in issues] == ["custom_pairs_invalid", "custom_pairs_invalid"]
    assert "group:Z:9" in issues[0].message or "group:Z:9" in issues[1].message
