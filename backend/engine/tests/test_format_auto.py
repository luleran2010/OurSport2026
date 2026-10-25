import pytest

from engine.bracket import build_bracket
from engine.format_auto import FormatCandidate, format_auto
from engine.rules.format import total_match_count
from engine.rules.presets import football_rules
from engine.rules.validate import validate_setup
from engine.schedule import build_schedule
from engine.tests.conftest import make_day, make_schedule

SEED = b"format-auto-test"


def shape(candidate: FormatCandidate) -> tuple[list[int], int, int, list[str], bool]:
    fmt, advancement = candidate.choice.format, candidate.choice.advancement
    knockout = fmt.knockout
    return (
        fmt.group_sizes,
        advancement.per_group,
        advancement.best_of_rest,
        [str(r) for r in knockout.rounds] if knockout else [],
        knockout.third_place_match if knockout else False,
    )


def test_sixteen_teams_get_four_groups_of_four_and_quarter_finals() -> None:
    candidates = format_auto(16, make_schedule())

    assert shape(candidates[0]) == (
        [4, 4, 4, 4],
        2,
        0,
        ["quarter_final", "semi_final", "final"],
        True,
    )
    assert candidates[0].summary == (
        "4 groups of 4 · top 2 → quarter-finals · third-place match · 32 matches"
    )


def test_twenty_four_teams_get_best_thirds_into_a_round_of_sixteen() -> None:
    policy = make_schedule(pitches=[f"p{i}" for i in range(1, 7)])

    best = format_auto(24, policy)[0]

    assert shape(best)[:4] == (
        [4] * 6,
        2,
        4,
        ["round_of_16", "quarter_final", "semi_final", "final"],
    )
    assert "4 best third-placed teams" in best.summary


def test_thirty_two_teams_get_eight_groups_of_four() -> None:
    policy = make_schedule(
        days=[make_day(d, "09:00", "20:00") for d in (12, 13, 14)],
        pitches=[f"p{i}" for i in range(1, 7)],
    )

    assert shape(format_auto(32, policy)[0])[:3] == ([4] * 8, 2, 0)


@pytest.mark.parametrize("team_count", [3, 4, 5, 6, 7, 9, 10, 12, 13, 16, 20])
def test_every_candidate_is_valid_and_fits_the_days_and_pitches(team_count: int) -> None:
    policy = make_schedule()

    candidates = format_auto(team_count, policy)

    assert candidates
    assert len({c.summary for c in candidates}) == len(candidates)
    for candidate in candidates:
        fmt = candidate.choice.format
        assert fmt.team_count == team_count
        rules = football_rules("football_gd_first", candidate.choice)
        assert validate_setup(rules, fmt, schedule=policy) == []
        assert candidate.matches == total_match_count(fmt)
        assert candidate.min_matches_per_team <= candidate.max_matches_per_team
        bracket = build_bracket(fmt, candidate.choice.advancement) if fmt.knockout else None
        groups = [[f"t{g}-{i}" for i in range(size)] for g, size in enumerate(fmt.group_sizes)]
        build_schedule(groups, bracket, policy, seed=SEED)


def test_small_tournaments_prefer_a_final_over_a_bare_league() -> None:
    best = format_auto(4, make_schedule())[0]

    assert shape(best)[:4] == ([4], 2, 0, ["final"])


def test_every_team_plays_at_least_two_matches_where_possible() -> None:
    for team_count in (6, 9, 12):
        assert format_auto(team_count, make_schedule())[0].min_matches_per_team >= 2


def test_nothing_fits_in_too_little_time() -> None:
    policy = make_schedule(days=[make_day(12, "09:00", "11:00")], pitches=["p1"])

    assert format_auto(16, policy) == []


def test_drops_the_third_place_match_when_only_that_does_not_fit() -> None:
    # Day two ends at 15:00: QF, SF and final fit after the group stage, a 3P match does not.
    policy = make_schedule(days=[make_day(12), make_day(13, "09:00", "15:00")])

    candidates = format_auto(16, policy)

    groups_of_four = [c for c in candidates if shape(c)[:3] == ([4, 4, 4, 4], 2, 0)]
    assert shape(groups_of_four[0]) == (
        [4, 4, 4, 4],
        2,
        0,
        ["quarter_final", "semi_final", "final"],
        False,
    )
    assert groups_of_four[0].summary.endswith("→ quarter-finals · 31 matches")


def test_limit_caps_the_list() -> None:
    assert len(format_auto(12, make_schedule(), limit=2)) == 2
