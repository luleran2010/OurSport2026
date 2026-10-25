import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from engine.rules.format import FormatSpec, groups_then_knockout
from engine.rules.issues import Issue
from engine.rules.schedule_policy import FixedSlot, slots_per_pitch, total_slots
from engine.rules.seeding import FixedPlacement, SeedingPolicy, SeedingSource, Separation
from engine.rules.validate import validate_schedule, validate_seeding
from engine.tests.conftest import make_day, make_rules, make_schedule

SIXTEEN = groups_then_knockout([4, 4, 4, 4], per_group=2).format


def codes(issues: list[Issue]) -> list[str]:
    return [issue.code for issue in issues]


def policy(**overrides: object) -> SeedingPolicy:
    values: dict[str, object] = {"source": [SeedingSource.PREVIOUS_PLACEMENT, SeedingSource.NONE]}
    values.update(overrides)
    return SeedingPolicy.model_validate(values)


# --- seeding -------------------------------------------------------------------------------


def test_previous_semi_finalists_apart_is_valid(team_ids: list[str]) -> None:
    separation = Separation(teams=team_ids[:4], reason="2025 semi-finalists")

    assert validate_seeding(policy(separations=[separation]), SIXTEEN, team_ids) == []


def test_unsatisfiable_separation_explains_why(team_ids: list[str]) -> None:
    separation = Separation(teams=team_ids[:6], reason="2025 quarter-finalists")

    issues = validate_seeding(policy(separations=[separation]), SIXTEEN, team_ids)

    assert codes(issues) == ["separation_unsatisfiable"]
    assert issues[0].message == (
        "6 teams (2025 quarter-finalists) must be in different groups, but there are only 4 groups"
    )


def test_max_per_group_separation_counts_capacity(team_ids: list[str]) -> None:
    fits = Separation(kind="max_per_group", teams=team_ids[:8], max_per_group=2, reason="same club")
    too_many = Separation(
        kind="max_per_group", teams=team_ids[:9], max_per_group=2, reason="same club"
    )

    assert validate_seeding(policy(separations=[fits]), SIXTEEN, team_ids) == []
    assert codes(validate_seeding(policy(separations=[too_many]), SIXTEEN, team_ids)) == [
        "separation_unsatisfiable"
    ]


@given(k=st.integers(min_value=2, max_value=16), groups=st.integers(min_value=1, max_value=8))
def test_distinct_groups_is_satisfiable_exactly_when_teams_fit(k: int, groups: int) -> None:
    team_ids = [f"t{i}" for i in range(groups * 4)]
    fmt = FormatSpec(team_count=groups * 4, group_sizes=[4] * groups)
    separation = Separation(teams=team_ids[: min(k, len(team_ids))], reason="seeds")

    issues = validate_seeding(policy(separations=[separation]), fmt, team_ids)

    assert ("separation_unsatisfiable" in codes(issues)) == (min(k, len(team_ids)) > groups)


def test_separation_with_unknown_team_is_rejected(team_ids: list[str]) -> None:
    separation = Separation(teams=["t01", "ghost"], reason="seeds")

    issues = validate_seeding(policy(separations=[separation]), SIXTEEN, team_ids)

    assert codes(issues) == ["separation_unknown_team"]
    assert issues[0].path == "seeding.separations[0].teams[1]"


def test_fixed_placement_must_fit_the_format(team_ids: list[str]) -> None:
    fixed = [FixedPlacement(team="t01", group_index=5)]

    assert codes(validate_seeding(policy(fixed=fixed), SIXTEEN, team_ids)) == [
        "fixed_placement_invalid"
    ]


def test_fixed_placements_cannot_break_a_separation(team_ids: list[str]) -> None:
    separation = Separation(teams=["t01", "t02"], reason="2025 finalists")
    fixed = [FixedPlacement(team="t01", group_index=0), FixedPlacement(team="t02", group_index=0)]

    issues = validate_seeding(policy(separations=[separation], fixed=fixed), SIXTEEN, team_ids)

    assert codes(issues) == ["fixed_conflicts_separation"]


def test_pots_need_groups(team_ids: list[str]) -> None:
    knockout = FormatSpec.model_validate(
        {
            "team_count": 16,
            "knockout": {"rounds": ["round_of_16", "quarter_final", "semi_final", "final"]},
        }
    )

    assert codes(validate_seeding(policy(), knockout, team_ids)) == ["pots_need_groups"]


def test_seeding_source_none_must_be_last(team_ids: list[str]) -> None:
    bad = policy(source=[SeedingSource.NONE, SeedingSource.RATING])

    assert codes(validate_seeding(bad, SIXTEEN, team_ids)) == ["seeding_source_invalid"]


# --- schedule ------------------------------------------------------------------------------


def test_three_days_four_pitches_fit_a_sixteen_team_cup() -> None:
    assert validate_schedule(make_schedule(), SIXTEEN, make_rules()) == []


def test_slots_respect_blocked_breaks() -> None:
    # 09:00-19:00 = 600 min; slot = 45 + 5. Without breaks: (600 + 5) // 50 = 12.
    plain = make_day(12)
    # A 13:00-14:00 prayer/meal break splits the day into 240 and 300 minutes: 4 + 6.
    with_break = make_day(12, blocked=[(dt.time(13), dt.time(14))])

    assert slots_per_pitch(plain, 45, 5) == 12
    assert slots_per_pitch(with_break, 45, 5) == 4 + 6


def test_too_few_slots_names_both_numbers() -> None:
    schedule = make_schedule(days=[make_day(12, "09:00", "13:00")], pitches=["p1", "p2"])

    issues = validate_schedule(schedule, SIXTEEN, make_rules())

    assert "schedule_too_few_slots" in codes(issues)
    message = next(i.message for i in issues if i.code == "schedule_too_few_slots")
    assert message == "31 matches need 31 slots, but the days and pitches give 8"


def test_simultaneous_last_round_needs_a_pitch_per_match() -> None:
    schedule = make_schedule(pitches=["p1"])

    issues = validate_schedule(schedule, SIXTEEN, make_rules())
    relaxed = validate_schedule(
        schedule.model_copy(update={"simultaneous_last_group_round": False}),
        SIXTEEN,
        make_rules(),
    )

    assert "schedule_last_round_needs_pitches" in codes(issues)
    assert "schedule_last_round_needs_pitches" not in codes(relaxed)


def test_team_needs_enough_days_for_its_matches() -> None:
    schedule = make_schedule(days=[make_day(12)], pitches=["p1", "p2", "p3", "p4"])

    issues = validate_schedule(schedule, SIXTEEN, make_rules())

    assert "schedule_team_days_insufficient" in codes(issues)


def test_match_slot_shorter_than_the_rules_is_rejected() -> None:
    # Rules: 2 x 20 min + 5 min half-time = 45 min.
    issues = validate_schedule(make_schedule(match_minutes=40), SIXTEEN, make_rules())

    assert codes(issues) == ["match_too_short_for_rules"]


def test_days_must_be_in_order_and_windows_sane() -> None:
    schedule = make_schedule(days=[make_day(13), make_day(12, "18:00", "09:00"), make_day(14)])

    found = codes(validate_schedule(schedule, SIXTEEN, make_rules()))

    assert "schedule_days_invalid" in found
    assert "schedule_window_invalid" in found


def test_blocked_time_outside_the_window_is_rejected() -> None:
    day = make_day(12, blocked=[(dt.time(20), dt.time(21))])

    issues = validate_schedule(
        make_schedule(days=[day, make_day(13), make_day(14)]), SIXTEEN, make_rules()
    )

    assert codes(issues) == ["schedule_window_invalid"]
    assert issues[0].path == "schedule.days[0].blocked[0]"


def test_fixed_slot_must_name_a_real_match_and_day() -> None:
    schedule = make_schedule(
        fixed_slots=[
            FixedSlot(match_code="F", date=dt.date(2026, 6, 14), start=dt.time(17)),
            FixedSlot(match_code="QF9", date=dt.date(2026, 6, 14), start=dt.time(10)),
            FixedSlot(match_code="A1", date=dt.date(2026, 7, 1), start=dt.time(10)),
        ]
    )

    issues = validate_schedule(schedule, SIXTEEN, make_rules())

    assert [i.path for i in issues] == ["schedule.fixed_slots[1]", "schedule.fixed_slots[2]"]
    assert codes(issues) == ["fixed_slot_invalid", "fixed_slot_invalid"]


def test_duplicate_pitches_are_rejected() -> None:
    issues = validate_schedule(make_schedule(pitches=["p1", "p1"]), SIXTEEN, make_rules())

    assert "schedule_pitches_invalid" in codes(issues)


@given(
    pitches=st.integers(min_value=1, max_value=6),
    end_hour=st.integers(min_value=12, max_value=22),
    match_minutes=st.integers(min_value=20, max_value=90),
)
def test_more_pitches_or_longer_days_never_lose_slots(
    pitches: int, end_hour: int, match_minutes: int
) -> None:
    def slots(pitch_count: int, end: int) -> int:
        days = [make_day(12, "09:00", f"{end:02d}:00")]
        return total_slots(
            make_schedule(
                days=days,
                pitches=[f"p{i}" for i in range(pitch_count)],
                match_minutes=match_minutes,
            )
        )

    assert slots(pitches + 1, end_hour) >= slots(pitches, end_hour)
    assert slots(pitches, min(end_hour + 1, 23)) >= slots(pitches, end_hour)
