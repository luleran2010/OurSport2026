import dataclasses
import datetime as dt
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import combinations, pairwise
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.bracket import Bracket, build_bracket
from engine.rules.format import (
    FormatChoice,
    all_match_codes,
    groups_then_knockout,
    knockout_only,
    league,
)
from engine.rules.schedule_policy import DayWindow, FixedSlot, SchedulePolicy, total_slots
from engine.schedule import (
    MatchPostponed,
    PitchClosed,
    PitchDelay,
    ScheduledMatch,
    ScheduleInfeasible,
    SchedulePlan,
    TeamWithdrawn,
    berger_rounds,
    build_schedule,
    reschedule,
    schedule_violations,
    suggest_relaxations,
)
from engine.tests.conftest import make_day, make_schedule

SEED = b"schedule-test"


def team_groups(sizes: Sequence[int]) -> list[list[str]]:
    groups, next_id = [], 1
    for size in sizes:
        groups.append([f"t{next_id + i:02d}" for i in range(size)])
        next_id += size
    return groups


def tournament(choice: FormatChoice) -> tuple[list[list[str]], Bracket | None]:
    bracket = build_bracket(choice.format, choice.advancement) if choice.format.knockout else None
    return team_groups(choice.format.group_sizes), bracket


def cup16() -> tuple[FormatChoice, list[list[str]], Bracket | None]:
    choice = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)
    return (choice, *tournament(choice))


def by_code(plan: SchedulePlan) -> dict[str, ScheduledMatch]:
    return {m.code: m for m in plan.matches}


def local_minutes(match: ScheduledMatch) -> int:
    return match.local_time.hour * 60 + match.local_time.minute


# --- Berger round robin ----------------------------------------------------------------------


@pytest.mark.parametrize("size", [2, 3, 4, 5, 6, 7, 8])
def test_berger_every_pair_meets_once_and_nobody_plays_twice_a_round(size: int) -> None:
    teams = [f"t{i}" for i in range(size)]

    rounds = berger_rounds(teams)

    assert len(rounds) == (size - 1 if size % 2 == 0 else size)
    meetings = Counter(frozenset(pair) for round_ in rounds for pair in round_)
    assert set(meetings) == {frozenset(pair) for pair in combinations(teams, 2)}
    assert set(meetings.values()) == {1}
    for round_ in rounds:
        playing = [team for pair in round_ for team in pair]
        assert len(playing) == len(set(playing))


@pytest.mark.parametrize("size", [4, 6, 8])
def test_berger_home_and_away_are_balanced(size: int) -> None:
    teams = [f"t{i}" for i in range(size)]
    home = Counter(h for round_ in berger_rounds(teams) for h, _ in round_)

    assert all(abs(home[t] - (size - 1 - home[t])) <= 1 for t in teams)


def test_berger_group_of_four_ends_with_the_top_seeds_meeting() -> None:
    rounds = berger_rounds(["a1", "a2", "a3", "a4"])

    assert {frozenset(p) for p in rounds[-1]} == {
        frozenset({"a1", "a2"}),
        frozenset({"a3", "a4"}),
    }


# --- building --------------------------------------------------------------------------------


def test_community_cup_fills_three_days_group_stage_first_then_knockout() -> None:
    choice, groups, bracket = cup16()
    policy = make_schedule()

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert sorted(m.code for m in plan.matches) == sorted(all_match_codes(choice.format))
    assert schedule_violations(plan, policy) == []
    assert plan.quality.hard_violations == 0
    group_days = {m.day for m in plan.matches if m.stage == "group"}
    knockout_days = {m.day for m in plan.matches if m.stage != "group"}
    assert group_days == {1, 2}
    assert knockout_days == {3}
    assert plan.quality.group_stage_last_day == 2


def test_final_is_in_the_best_slot_after_the_third_place_match() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()

    matches = by_code(build_schedule(groups, bracket, policy, seed=SEED))

    final, third = matches["F"], matches["3P"]
    assert final.pitch == "p1"
    assert final.day == 3
    assert final.start == max(m.start for m in matches.values())
    assert third.end <= final.start
    assert final.starts_at == "2026-06-14T15:10:00Z"  # 18:10 in Helsinki (UTC+3)
    assert final.local_time == dt.time(18, 10)


def test_last_group_round_kicks_off_together() -> None:
    _, groups, bracket = cup16()

    plan = build_schedule(groups, bracket, make_schedule(), seed=SEED)

    for letter in "ABCD":
        last = [m for m in plan.matches if m.group == letter and m.round == 3]
        assert len(last) == 2
        assert len({m.start for m in last}) == 1
        assert len({m.pitch for m in last}) == 2


def test_group_matches_carry_teams_and_knockout_matches_their_placeholders() -> None:
    _, groups, bracket = cup16()

    matches = by_code(build_schedule(groups, bracket, make_schedule(), seed=SEED))

    a1 = matches["A1"]
    assert {a1.home, a1.away} <= set(groups[0])
    assert a1.home_source is None
    qf1 = matches["QF1"]
    assert (qf1.home, qf1.away) == (None, None)
    assert (qf1.home_source, qf1.away_source) == ("group:A:1", "group:B:2")
    assert set(qf1.teams) == set(groups[0]) | set(groups[1])
    assert set(qf1.depends_on) == {f"A{i}" for i in range(1, 7)} | {f"B{i}" for i in range(1, 7)}
    assert matches["F"].follows == ("3P",)


def test_same_seed_gives_the_same_plan() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()

    first = build_schedule(groups, bracket, policy, seed=SEED)
    second = build_schedule(groups, bracket, policy, seed=SEED)

    assert first == second


def test_main_pitch_is_shared_fairly() -> None:
    _, groups, bracket = cup16()

    plan = build_schedule(groups, bracket, make_schedule(), seed=SEED)

    # Six group kick-off times share the main pitch among four groups, and in a group of
    # four any two matches from different rounds share a team: two teams play there twice.
    on_main = Counter(
        team for m in plan.matches if m.stage == "group" and m.pitch == "p1" for team in m.teams
    )
    assert plan.quality.main_pitch_spread == 2
    assert sorted(on_main.values(), reverse=True)[:3] == [2, 2, 1]
    assert plan.quality.final_in_best_slot is True


def test_fixed_slot_is_honoured() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(
        fixed_slots=[
            FixedSlot(match_code="A1", date=dt.date(2026, 6, 12), start=dt.time(10, 0), pitch="p2")
        ]
    )

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    a1 = by_code(plan)["A1"]
    assert (a1.local_date, a1.local_time, a1.pitch) == (dt.date(2026, 6, 12), dt.time(10, 0), "p2")
    assert schedule_violations(plan, policy) == []


def test_prayer_and_meal_breaks_are_kept_free() -> None:
    _, groups, bracket = cup16()
    prayer = (dt.time(13, 0), dt.time(14, 0))
    policy = make_schedule(days=[make_day(d, blocked=[prayer]) for d in (12, 13, 14)])

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    for match in plan.matches:
        start = local_minutes(match)
        assert start + policy.match_minutes <= 13 * 60 or start >= 14 * 60
    assert schedule_violations(plan, policy) == []


def test_matches_per_day_and_rest_hold_for_every_team() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(max_matches_per_team_per_day=2, min_rest_minutes=90)

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    per_team: dict[str, list[ScheduledMatch]] = defaultdict(list)
    for match in plan.matches:
        if match.stage == "group":
            assert match.home is not None and match.away is not None
            per_team[match.home].append(match)
            per_team[match.away].append(match)
    for matches in per_team.values():
        assert max(Counter(m.day for m in matches).values()) <= 2
        ordered = sorted(matches, key=lambda m: m.start)
        assert all(b.start - a.end >= 90 for a, b in pairwise(ordered))
    assert schedule_violations(plan, policy) == []


def test_group_stage_can_be_finished_on_the_first_day() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(group_stage_ends_by_day=1)

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert plan.quality.group_stage_last_day == 1
    assert schedule_violations(plan, policy) == []


def test_league_is_spread_over_all_days() -> None:
    choice = league(6)
    groups, bracket = tournament(choice)
    policy = make_schedule(pitches=["p1", "p2", "p3"])

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert len(plan.matches) == 15
    assert {m.day for m in plan.matches} == {1, 2, 3}
    assert schedule_violations(plan, policy) == []


def test_double_round_robin_plays_every_pair_home_and_away() -> None:
    choice = league(4, double=True)
    groups, bracket = tournament(choice)

    plan = build_schedule(groups, bracket, make_schedule(), seed=SEED, group_rounds=2)

    pairs = Counter((m.home, m.away) for m in plan.matches)
    assert len(plan.matches) == 12
    assert set(pairs.values()) == {1}
    assert all((away, home) in pairs for home, away in pairs)


def test_knockout_only_orders_the_rounds() -> None:
    choice = knockout_only(8, third_place_match=True)
    groups, bracket = tournament(choice)
    policy = make_schedule(days=[make_day(12)])

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    matches = by_code(plan)
    assert len(matches) == 8
    assert matches["SF1"].start >= matches["QF2"].end + policy.min_rest_minutes
    assert schedule_violations(plan, policy) == []


def test_too_little_time_is_infeasible_with_counts() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(days=[make_day(12, "09:00", "13:00")], pitches=["p1"])

    with pytest.raises(ScheduleInfeasible) as raised:
        build_schedule(groups, bracket, policy, seed=SEED)

    assert raised.value.matches == 32
    assert raised.value.slots == total_slots(policy)
    assert raised.value.unplaced


def test_knockout_needing_more_matches_per_day_than_allowed_is_infeasible() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(days=[make_day(12)], pitches=[f"p{i}" for i in range(1, 9)])

    with pytest.raises(ScheduleInfeasible):
        build_schedule(groups, bracket, policy, seed=SEED)


# --- the independent checker -----------------------------------------------------------------


def moved(plan: SchedulePlan, code: str, other: str) -> SchedulePlan:
    """`code` moved onto the slot of `other`."""
    target = by_code(plan)[other]
    matches = tuple(
        dataclasses.replace(
            m,
            day=target.day,
            pitch=target.pitch,
            start=target.start,
            end=target.end,
            local_date=target.local_date,
            local_time=target.local_time,
        )
        if m.code == code
        else m
        for m in plan.matches
    )
    return dataclasses.replace(plan, matches=matches)


def kinds(plan: SchedulePlan, policy: SchedulePolicy) -> set[str]:
    return {v.kind for v in schedule_violations(plan, policy)}


def test_checker_finds_a_double_booked_pitch() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()
    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert "pitch_double_booked" in kinds(moved(plan, "C1", "A1"), policy)


def test_checker_finds_a_team_without_rest() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()
    plan = build_schedule(groups, bracket, policy, seed=SEED)
    a1, a3 = by_code(plan)["A1"], by_code(plan)["A3"]
    assert {a1.home, a1.away} & {a3.home, a3.away}
    start = a1.end + policy.break_minutes  # right after A1: no rest
    local = dt.datetime.combine(a1.local_date, a1.local_time) + dt.timedelta(
        minutes=start - a1.start
    )
    soon = dataclasses.replace(
        a3,
        day=a1.day,
        start=start,
        end=start + policy.match_minutes,
        local_date=local.date(),
        local_time=local.time(),
    )
    plan = dataclasses.replace(
        plan, matches=tuple(soon if m.code == "A3" else m for m in plan.matches)
    )

    assert "team_rest" in kinds(plan, policy)


def test_checker_finds_knockout_before_its_group_ends() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()
    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert "dependency_order" in kinds(moved(plan, "QF1", "A1"), policy)


def test_checker_finds_a_split_last_round_and_a_moved_fixed_slot() -> None:
    _, groups, bracket = cup16()
    fixed = FixedSlot(match_code="F", date=dt.date(2026, 6, 14), start=dt.time(18, 10), pitch="p1")
    policy = make_schedule(fixed_slots=[fixed])
    plan = build_schedule(groups, bracket, policy, seed=SEED)
    last_a = [m.code for m in plan.matches if m.group == "A" and m.round == 3]

    assert "last_round_not_together" in kinds(moved(plan, last_a[0], "A1"), policy)
    assert "fixed_slot_moved" in kinds(moved(plan, "F", "SF1"), policy)


def test_checker_finds_a_match_in_a_break() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule()
    plan = build_schedule(groups, bracket, policy, seed=SEED)
    prayer = make_schedule(
        days=[make_day(d, blocked=[(dt.time(9, 0), dt.time(10, 0))]) for d in (12, 13, 14)]
    )

    assert "outside_playing_time" in kinds(plan, prayer)


# --- property: any tournament that fits is scheduled without breaking a hard constraint ------


@st.composite
def setups(draw: st.DrawFn) -> tuple[FormatChoice, SchedulePolicy, int]:
    shape = draw(st.sampled_from(["groups", "league", "knockout"]))
    if shape == "groups":
        group_count = draw(st.sampled_from([1, 2, 4]))
        sizes = draw(st.lists(st.integers(3, 5), min_size=group_count, max_size=group_count))
        per_group = draw(st.sampled_from([1, 2]))
        try:
            choice = groups_then_knockout(
                sizes, per_group=per_group, third_place_match=draw(st.booleans())
            )
        except ValueError:
            assume(False)
            raise
        knockout = choice.format.knockout
        assume(knockout is None or not knockout.third_place_match or len(knockout.rounds) > 1)
    elif shape == "league":
        choice = league(draw(st.integers(3, 6)))
    else:
        choice = knockout_only(draw(st.sampled_from([4, 8])), third_place_match=draw(st.booleans()))
    day_count = draw(st.integers(1, 3))
    blocked = draw(st.booleans())
    days = [
        make_day(
            12 + d,
            f"{draw(st.integers(8, 10)):02d}:00",
            f"{draw(st.integers(17, 21)):02d}:00",
            blocked=[(dt.time(13, 0), dt.time(13, 30))] if blocked else [],
            utc_offset_minutes=draw(st.sampled_from([120, 180, 360])),
        )
        for d in range(day_count)
    ]
    match_minutes = draw(st.integers(20, 50))
    policy = SchedulePolicy(
        time_zone="Europe/Helsinki",
        days=days,
        pitches=[f"p{i}" for i in range(1, draw(st.integers(1, 4)) + 1)],
        match_minutes=match_minutes,
        break_minutes=draw(st.integers(0, 10)),
        min_rest_minutes=draw(st.integers(0, 90)),
        max_matches_per_team_per_day=draw(st.integers(1, 4)),
        simultaneous_last_group_round=draw(st.booleans()),
    )
    return choice, policy, draw(st.integers(0, 2**32))


@settings(max_examples=120, deadline=None)
@given(setups())
def test_property_schedules_never_break_hard_constraints(
    setup: tuple[FormatChoice, SchedulePolicy, int],
) -> None:
    choice, policy, seed = setup
    groups, bracket = tournament(choice)

    try:
        plan = build_schedule(groups, bracket, policy, seed=seed.to_bytes(8, "big"))
    except ScheduleInfeasible:
        return

    assert sorted(m.code for m in plan.matches) == sorted(all_match_codes(choice.format))
    assert schedule_violations(plan, policy) == []
    starts = {m.code: m.start for m in plan.matches}
    for match in plan.matches:
        for dependency in match.depends_on:
            assert starts[dependency] < match.start


# --- rescheduling ----------------------------------------------------------------------------

DAY_ONE_NOON = "2026-06-12T09:00:00Z"  # 12:00 in Helsinki


def planned() -> tuple[SchedulePlan, SchedulePolicy]:
    _, groups, bracket = cup16()
    policy = make_schedule()
    return build_schedule(groups, bracket, policy, seed=SEED), policy


def started_before(plan: SchedulePlan, cutoff: str) -> list[ScheduledMatch]:
    limit = dt.datetime.fromisoformat(cutoff)
    return [m for m in plan.matches if dt.datetime.fromisoformat(m.starts_at) < limit]


def test_closed_pitch_moves_its_later_matches_and_keeps_started_ones() -> None:
    plan, policy = planned()
    closed = next(m.pitch for m in plan.matches if m.starts_at >= DAY_ONE_NOON)

    new = reschedule(plan, frozen_until=DAY_ONE_NOON, changes=[PitchClosed(closed)], policy=policy)

    for match in started_before(plan, DAY_ONE_NOON):
        assert by_code(new)[match.code] == match
    assert not [m for m in new.matches if m.pitch == closed and m.starts_at >= DAY_ONE_NOON]
    on_closed = {m.code for m in plan.matches if m.pitch == closed and m.starts_at >= DAY_ONE_NOON}
    assert on_closed <= set(new.moved)
    assert schedule_violations(new, policy, check_fixed=False) == []


def test_pitch_running_late_moves_only_what_it_must() -> None:
    plan, policy = planned()
    running = next(m for m in plan.matches if m.day == 1 and m.round == 2)
    cutoff = running.starts_at.replace(":00Z", ":01Z")

    new = reschedule(
        plan, frozen_until=cutoff, changes=[PitchDelay(running.pitch, 20)], policy=policy
    )

    assert by_code(new)[running.code].end == running.end + 20
    assert all(by_code(new)[m.code].start == m.start for m in started_before(plan, cutoff))
    assert 1 <= len(new.moved) <= 4
    assert schedule_violations(new, policy, check_fixed=False) == []


def test_withdrawn_team_unplayed_matches_become_walkovers() -> None:
    plan, policy = planned()
    team = next(m.home for m in plan.matches if m.group == "B")
    assert team is not None
    unplayed = {
        m.code for m in plan.matches if team in (m.home, m.away) and m.starts_at >= DAY_ONE_NOON
    }

    new = reschedule(plan, frozen_until=DAY_ONE_NOON, changes=[TeamWithdrawn(team)], policy=policy)

    assert unplayed
    assert set(new.walkovers) == unplayed
    assert not unplayed & set(by_code(new))
    assert new.moved == ()


def test_postponed_match_moves_later_and_nothing_else_needs_to() -> None:
    plan, policy = planned()
    target = next(m for m in plan.matches if m.group == "A" and m.round == 1)

    new = reschedule(
        plan,
        frozen_until="2026-06-12T05:00:00Z",
        changes=[MatchPostponed(target.code)],
        policy=policy,
    )

    assert by_code(new)[target.code].start > target.start
    assert target.code in new.moved
    assert schedule_violations(new, policy, check_fixed=False) == []


def test_postponed_until_a_given_time() -> None:
    plan, policy = planned()
    target = next(m for m in plan.matches if m.group == "C" and m.round == 1)

    new = reschedule(
        plan,
        frozen_until="2026-06-12T05:00:00Z",
        changes=[MatchPostponed(target.code, not_before="2026-06-12T14:00:00Z")],
        policy=policy,
    )

    assert by_code(new)[target.code].starts_at >= "2026-06-12T14:00:00Z"
    assert schedule_violations(new, policy, check_fixed=False) == []


def test_reschedule_that_cannot_fit_is_infeasible() -> None:
    plan, policy = planned()
    every_pitch = [PitchClosed(p) for p in policy.pitches]

    with pytest.raises(ScheduleInfeasible):
        reschedule(plan, frozen_until=DAY_ONE_NOON, changes=every_pitch, policy=policy)


changes_strategy = st.one_of(
    st.builds(PitchClosed, st.sampled_from(["p1", "p2", "p3", "p4"])),
    st.builds(PitchDelay, st.sampled_from(["p1", "p2", "p3", "p4"]), st.integers(5, 60)),
    st.builds(TeamWithdrawn, st.sampled_from([f"t{i:02d}" for i in range(1, 17)])),
    st.builds(MatchPostponed, st.sampled_from(["A1", "B2", "C3", "D4", "A5", "QF1", "SF2"])),
)


@settings(max_examples=60, deadline=None)
@given(
    hours=st.integers(0, 50),
    changes=st.lists(changes_strategy, min_size=1, max_size=3),
)
def test_property_reschedule_keeps_started_matches_and_hard_constraints(
    hours: int, changes: list[Any]
) -> None:
    plan, policy = planned()
    cutoff = (dt.datetime(2026, 6, 12, 6, 0) + dt.timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        new = reschedule(plan, frozen_until=cutoff, changes=changes, policy=policy)
    except ScheduleInfeasible:
        return

    new_matches = by_code(new)
    for match in started_before(plan, cutoff):
        kept = new_matches[match.code]
        assert (kept.start, kept.pitch) == (match.start, match.pitch)
    for code in new.moved:
        assert by_code(plan)[code].starts_at >= cutoff
        assert new_matches[code].starts_at >= cutoff
    assert schedule_violations(new, policy, check_fixed=False) == []


# --- relaxations -----------------------------------------------------------------------------


def test_relaxations_for_an_infeasible_setup_come_with_slot_counts() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(pitches=["p1"])
    with pytest.raises(ScheduleInfeasible):
        build_schedule(groups, bracket, policy, seed=SEED)

    relaxations = suggest_relaxations(groups, bracket, policy, seed=SEED)

    assert relaxations
    assert relaxations[0].feasible
    feasible = [r for r in relaxations if r.feasible]
    assert "add_pitch" in {r.kind for r in feasible}
    for relaxation in relaxations:
        assert relaxation.slots == total_slots(relaxation.policy)
        assert relaxation.summary
    for relaxation in feasible:
        build_schedule(groups, bracket, relaxation.policy, seed=SEED)
    add_pitch = next(r for r in feasible if r.kind == "add_pitch")
    assert add_pitch.slots > total_slots(policy)


def test_no_relaxations_when_the_schedule_fits() -> None:
    _, groups, bracket = cup16()

    assert suggest_relaxations(groups, bracket, make_schedule(), seed=SEED) == []


def test_shorter_matches_suggests_the_smallest_cut_that_fits() -> None:
    _, groups, bracket = cup16()
    policy = make_schedule(
        days=[make_day(12, "09:00", "17:00"), make_day(13, "09:00", "17:00")],
        pitches=["p1", "p2", "p3"],
    )
    with pytest.raises(ScheduleInfeasible):
        build_schedule(groups, bracket, policy, seed=SEED)

    relaxations = suggest_relaxations(groups, bracket, policy, seed=SEED)

    shorter = next(r for r in relaxations if r.kind == "shorter_matches")
    assert shorter.feasible
    assert shorter.policy.match_minutes < policy.match_minutes
    longer_cut = shorter.policy.model_copy(
        update={"match_minutes": shorter.policy.match_minutes + 5}
    )
    with pytest.raises(ScheduleInfeasible):
        build_schedule(groups, bracket, longer_cut, seed=SEED)


# --- performance -----------------------------------------------------------------------------


def test_thirty_two_teams_three_days_six_pitches_is_fast() -> None:
    choice = groups_then_knockout([4] * 8, per_group=2, third_place_match=True)
    groups, bracket = tournament(choice)
    policy = make_schedule(
        days=[make_day(d, "09:00", "20:00") for d in (12, 13, 14)],
        pitches=[f"p{i}" for i in range(1, 7)],
    )

    started = time.perf_counter()
    plan = build_schedule(groups, bracket, policy, seed=SEED)
    elapsed = time.perf_counter() - started

    assert len(plan.matches) == 64
    assert schedule_violations(plan, policy) == []
    assert elapsed < 5


def test_window_day_offsets_are_used_for_utc_times() -> None:
    choice = league(4)
    groups, bracket = tournament(choice)
    winter = DayWindow(
        date=dt.date(2026, 12, 5),
        start=dt.time(10, 0),
        end=dt.time(16, 0),
        utc_offset_minutes=120,
    )
    policy = make_schedule(days=[winter], pitches=["p1", "p2"])

    plan = build_schedule(groups, bracket, policy, seed=SEED)

    assert plan.matches[0].starts_at == "2026-12-05T08:00:00Z"
    assert plan.matches[0].local_time == dt.time(10, 0)
