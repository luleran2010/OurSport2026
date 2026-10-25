from collections.abc import Mapping
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from engine.rules.config import AdvancementRule, PointsRule, Tiebreaker
from engine.rules.issues import InvalidConfig, Issue
from engine.rules.validate import ensure_valid, validate_rule_config
from engine.sports.base import SportRules
from engine.sports.football import FOOTBALL
from engine.sports.registry import SPORTS, UnknownSport, get_sport
from engine.tests.conftest import make_rules


def codes(issues: list[Issue]) -> list[str]:
    return [issue.code for issue in issues]


def test_valid_config_has_no_issues() -> None:
    assert validate_rule_config(make_rules()) == []


def test_registry_knows_this_release_sports() -> None:
    assert get_sport("football") is FOOTBALL
    assert set(SPORTS) == {"football", "futsal"}


def test_unknown_sport_is_rejected() -> None:
    with pytest.raises(UnknownSport):
        get_sport("quidditch")

    issues = validate_rule_config(make_rules(sport="quidditch"))

    assert codes(issues) == ["unknown_sport"]
    assert "quidditch" in issues[0].message
    assert "football" in issues[0].message


def test_unknown_outcome_key_is_named_with_the_expected_keys() -> None:
    rules = make_rules(points=PointsRule(table={"win": 3, "draw": 1, "loss": 0, "tie": 1}))

    issues = validate_rule_config(rules)

    assert codes(issues) == ["unknown_outcome_key"]
    assert issues[0].path == "points.table.tie"
    assert issues[0].message == (
        "'tie' is not an outcome in football; expected one of: win, draw, loss"
    )


def test_missing_outcome_key_is_reported() -> None:
    issues = validate_rule_config(make_rules(points=PointsRule(table={"win": 3, "loss": 0})))

    assert codes(issues) == ["missing_outcome_key"]
    assert issues[0].path == "points.table.draw"


def test_win_must_be_worth_more_than_loss() -> None:
    issues = validate_rule_config(
        make_rules(points=PointsRule(table={"win": 0, "draw": 1, "loss": 1}))
    )

    assert "invalid_points" in codes(issues)


@given(st.sets(st.sampled_from(["win", "draw", "loss", "tie", "ot_win", "bonus"]), min_size=1))
def test_points_table_issues_name_exactly_the_wrong_keys(keys: set[str]) -> None:
    table = dict.fromkeys(keys, 1) | ({"win": 3} if "win" in keys else {})
    rules = make_rules(points=PointsRule(table=table))

    issues = [i for i in validate_rule_config(rules) if i.code != "invalid_points"]

    expected = set(FOOTBALL.outcome_keys)
    assert {i.path for i in issues if i.code == "unknown_outcome_key"} == {
        f"points.table.{k}" for k in keys - expected
    }
    assert {i.path for i in issues if i.code == "missing_outcome_key"} == {
        f"points.table.{k}" for k in expected - keys
    }


def test_tiebreakers_must_start_with_points() -> None:
    issues = validate_rule_config(
        make_rules(tiebreakers=[Tiebreaker.SCORE_DIFF, Tiebreaker.POINTS])
    )

    assert codes(issues) == ["tiebreaker_order"]
    assert issues[0].path == "tiebreakers[0]"


def test_duplicate_tiebreaker_is_reported() -> None:
    issues = validate_rule_config(
        make_rules(tiebreakers=[Tiebreaker.POINTS, Tiebreaker.SCORE_DIFF, Tiebreaker.SCORE_DIFF])
    )

    assert codes(issues) == ["tiebreaker_duplicate"]
    assert issues[0].path == "tiebreakers[2]"


def test_draw_lots_must_be_last() -> None:
    issues = validate_rule_config(
        make_rules(tiebreakers=[Tiebreaker.POINTS, Tiebreaker.DRAW_LOTS, Tiebreaker.SCORE_DIFF])
    )

    assert codes(issues) == ["draw_lots_not_last"]


class _NoHeadToHeadSport:
    """A sport whose rules do not allow head-to-head tiebreakers."""

    code = "simple"
    outcome_keys: tuple[str, ...] = ("win", "loss")
    supported_tiebreakers = frozenset(
        {Tiebreaker.POINTS, Tiebreaker.SCORE_DIFF, Tiebreaker.DRAW_LOTS}
    )
    fair_play_keys: tuple[str, ...] = ()

    def match_rules_issues(self, match: Mapping[str, Any]) -> list[Issue]:
        return []

    def walkover_issues(self, walkover: Mapping[str, Any]) -> list[Issue]:
        return []

    def knockout_issues(self, match: Mapping[str, Any], uses_extra_time: bool) -> list[Issue]:
        return []

    def match_duration_minutes(self, match: Mapping[str, Any]) -> int:
        return 30


def test_tiebreaker_not_supported_by_the_sport_is_rejected() -> None:
    sport: SportRules = _NoHeadToHeadSport()
    rules = make_rules(
        sport="simple",
        points=PointsRule(table={"win": 2, "loss": 0}),
        tiebreakers=[Tiebreaker.POINTS, Tiebreaker.HEAD_TO_HEAD_POINTS],
        fair_play_points={},
    )

    issues = validate_rule_config(rules, sports={"simple": sport})

    assert codes(issues) == ["tiebreaker_not_supported"]
    assert issues[0].message == "head_to_head_points is not a tiebreaker in simple"


def test_head_to_head_cannot_rank_teams_from_different_groups() -> None:
    rules = make_rules(
        advancement=AdvancementRule(
            per_group=2,
            best_of_rest=2,
            rest_ranking=[Tiebreaker.POINTS, Tiebreaker.HEAD_TO_HEAD_POINTS],
        )
    )

    issues = validate_rule_config(rules)

    assert codes(issues) == ["tiebreaker_not_applicable"]
    assert issues[0].path == "advancement.rest_ranking[1]"


def test_best_of_rest_needs_a_ranking() -> None:
    issues = validate_rule_config(
        make_rules(advancement=AdvancementRule(per_group=2, best_of_rest=2))
    )

    assert codes(issues) == ["rest_ranking_missing"]


def test_invalid_football_match_rules_point_at_the_field() -> None:
    issues = validate_rule_config(make_rules(match={"periods": 2, "period_minutes": 0}))

    assert codes(issues) == ["invalid_match_rules"]
    assert issues[0].path == "match.period_minutes"


def test_unknown_football_match_rule_is_rejected() -> None:
    issues = validate_rule_config(make_rules(match={"periods": 2, "golden_goal": True}))

    assert codes(issues) == ["invalid_match_rules"]
    assert issues[0].path == "match.golden_goal"


def test_walkover_must_credit_a_win() -> None:
    issues = validate_rule_config(make_rules(walkover={"score_for": 0, "score_against": 0}))

    assert "invalid_walkover" in codes(issues)


def test_unknown_fair_play_key_is_rejected() -> None:
    issues = validate_rule_config(make_rules(fair_play_points={"yellow": 1, "orange": 2}))

    assert codes(issues) == ["unknown_fair_play_key"]
    assert issues[0].path == "fair_play_points.orange"


def test_unknown_config_field_is_rejected_at_parse_time() -> None:
    with pytest.raises(ValidationError):
        make_rules(golden_goal=True)


def test_ensure_valid_raises_with_every_issue() -> None:
    issues = validate_rule_config(
        make_rules(
            points=PointsRule(table={"win": 3, "tie": 1, "loss": 0}),
            tiebreakers=[Tiebreaker.SCORE_DIFF],
        )
    )

    with pytest.raises(InvalidConfig) as caught:
        ensure_valid(issues)

    assert len(caught.value.issues) == 3
    assert "points.table.tie" in str(caught.value)
