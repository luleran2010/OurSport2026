"""Every preset in the policy catalogue must produce a valid configuration."""

import pytest

from engine.rules.config import Tiebreaker
from engine.rules.format import FormatChoice
from engine.rules.presets import (
    CATALOGUE_VERSION,
    FORMAT_PRESETS,
    PRESETS,
    TIEBREAKER_PRESETS,
    PresetKind,
    football_match_rules,
    football_rules,
    schedule_community_weekend,
    schedule_junior,
    seeding_previous_placement,
    separation_same_organisation,
)
from engine.rules.validate import validate_setup
from engine.tests.conftest import make_day

DAYS = [make_day(12), make_day(13), make_day(14)]
PITCHES = ["p1", "p2", "p3", "p4", "p5", "p6"]


def test_catalogue_is_versioned_and_described() -> None:
    assert CATALOGUE_VERSION == 3
    for preset_id, preset in PRESETS.items():
        assert preset.id == preset_id
        assert preset.summary
        assert preset.practice


def test_every_catalogue_id_is_implemented() -> None:
    implemented = (
        set(TIEBREAKER_PRESETS)
        | set(FORMAT_PRESETS)
        | {
            "format_auto",  # engine.format_auto: needs the schedule policy, not just a count
            "seeding_previous_placement",
            "separation_same_organisation",
            "schedule_community_weekend",
            "schedule_junior",
        }
    )

    assert set(PRESETS) == implemented


def test_tiebreaker_presets_match_the_documented_order() -> None:
    assert TIEBREAKER_PRESETS["football_gd_first"] == (
        Tiebreaker.POINTS,
        Tiebreaker.SCORE_DIFF,
        Tiebreaker.SCORE_FOR,
        Tiebreaker.HEAD_TO_HEAD_POINTS,
        Tiebreaker.HEAD_TO_HEAD_DIFF,
        Tiebreaker.FAIR_PLAY,
        Tiebreaker.DRAW_LOTS,
    )
    assert TIEBREAKER_PRESETS["football_h2h_first"][:4] == (
        Tiebreaker.POINTS,
        Tiebreaker.HEAD_TO_HEAD_POINTS,
        Tiebreaker.HEAD_TO_HEAD_DIFF,
        Tiebreaker.HEAD_TO_HEAD_FOR,
    )


def _format(preset_id: str) -> FormatChoice:
    build = FORMAT_PRESETS[preset_id]
    # 4 teams: even a double league (6 matches per team) fits 3 days x 3 matches.
    return build(4) if preset_id.startswith("format_league") else build(None)


@pytest.mark.parametrize("format_id", sorted(FORMAT_PRESETS))
@pytest.mark.parametrize("tiebreaker_id", sorted(TIEBREAKER_PRESETS))
def test_every_format_and_tiebreaker_preset_validates(format_id: str, tiebreaker_id: str) -> None:
    choice = _format(format_id)
    team_ids = [f"t{i:02d}" for i in range(choice.format.team_count)]
    match = football_match_rules(period_minutes=15)
    rules = football_rules(tiebreaker_id, choice, match=match)
    schedule = schedule_community_weekend(DAYS, PITCHES, match)

    assert validate_setup(rules, choice.format, schedule=schedule, team_ids=team_ids) == []


def test_community_cup_presets_compose_into_a_valid_setup() -> None:
    choice = FORMAT_PRESETS["format_groups_of_4_qf"](None)
    team_ids = [f"t{i:02d}" for i in range(16)]
    match = football_match_rules(period_minutes=20, half_time_minutes=5)
    rules = football_rules("football_h2h_first", choice, match=match)
    seeding = seeding_previous_placement(
        group_count=4, previous_semi_finalists=team_ids[:4]
    ).model_copy(
        update={
            "separations": [
                *seeding_previous_placement(
                    group_count=4, previous_semi_finalists=team_ids[:4]
                ).separations,
                *separation_same_organisation(
                    {"club-x": team_ids[4:6], "club-y": team_ids[6:11]}, group_count=4
                ),
            ]
        }
    )
    schedule = schedule_community_weekend(DAYS, PITCHES[:4], match)

    assert schedule.match_minutes == 45
    assert schedule.min_rest_minutes == 60
    assert validate_setup(rules, choice.format, seeding, schedule, team_ids) == []


def test_same_organisation_separation_relaxes_when_a_club_has_more_teams_than_groups() -> None:
    separations = separation_same_organisation(
        {"big-club": [f"b{i}" for i in range(6)], "solo": ["s1"]}, group_count=4
    )

    assert len(separations) == 1
    assert separations[0].kind == "max_per_group"
    assert separations[0].max_per_group == 2


def test_junior_schedule_limits_matches_per_day() -> None:
    match = football_match_rules(periods=2, period_minutes=15, half_time_minutes=5)

    schedule = schedule_junior(DAYS, PITCHES, match)

    assert schedule.max_matches_per_team_per_day == 2
    assert schedule.min_rest_minutes >= 60


def test_preset_kinds_cover_the_catalogue() -> None:
    assert {preset.kind for preset in PRESETS.values()} == set(PresetKind)
