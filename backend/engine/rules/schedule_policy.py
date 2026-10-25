"""When and where matches can be played: days, windows, pitches and rest rules.

The engine never reads time-zone data (that would be file I/O): each day carries its own
UTC offset, computed by the app from `time_zone`. A per-day offset also covers a daylight
saving change during a tournament.
"""

import datetime as dt

from pydantic import Field

from engine.rules.base import RuleModel


class DayWindow(RuleModel):
    date: dt.date  # local date
    start: dt.time  # local time the first match may start
    end: dt.time  # local time the last match must end by
    utc_offset_minutes: int = Field(ge=-12 * 60, le=14 * 60)  # e.g. 180 for Helsinki summer
    # Prayer / meal breaks kept free of matches.
    blocked: list[tuple[dt.time, dt.time]] = Field(default_factory=list)


class FixedSlot(RuleModel):
    match_code: str  # "A1", "F"
    date: dt.date
    start: dt.time
    pitch: str | None = None


class SchedulePolicy(RuleModel):
    time_zone: str  # "Europe/Helsinki"; informational for the engine (see module docstring)
    days: list[DayWindow] = Field(min_length=1)
    pitches: list[str] = Field(min_length=1)  # pitch ids; the first is the main pitch
    match_minutes: int = Field(ge=1, le=240)  # pitch time per match, including half-time
    break_minutes: int = Field(ge=0, le=120)  # changeover between matches on a pitch
    min_rest_minutes: int = Field(ge=0)  # from a team's match end to its next start
    max_matches_per_team_per_day: int = Field(ge=1)
    simultaneous_last_group_round: bool = True
    group_stage_ends_by_day: int | None = Field(default=None, ge=1)  # 1-based day number
    fixed_slots: list[FixedSlot] = Field(default_factory=list)
    final_on_main_pitch_last_slot: bool = True


def minute_of_day(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def free_segments(day: DayWindow) -> list[tuple[int, int]]:
    """The day's window minus blocked periods, as (start, end) minutes since midnight."""
    start, end = minute_of_day(day.start), minute_of_day(day.end)
    if end <= start:
        return []
    segments = [(start, end)]
    for block_start_t, block_end_t in sorted(day.blocked):
        block_start, block_end = minute_of_day(block_start_t), minute_of_day(block_end_t)
        next_segments: list[tuple[int, int]] = []
        for seg_start, seg_end in segments:
            if block_end <= seg_start or block_start >= seg_end:
                next_segments.append((seg_start, seg_end))
                continue
            if block_start > seg_start:
                next_segments.append((seg_start, block_start))
            if block_end < seg_end:
                next_segments.append((block_end, seg_end))
        segments = next_segments
    return segments


def slots_in_segment(length: int, match_minutes: int, break_minutes: int) -> int:
    """Matches that fit back to back; no changeover is needed after the last one."""
    if length < match_minutes:
        return 0
    return (length + break_minutes) // (match_minutes + break_minutes)


def slots_per_pitch(day: DayWindow, match_minutes: int, break_minutes: int) -> int:
    return sum(
        slots_in_segment(end - start, match_minutes, break_minutes)
        for start, end in free_segments(day)
    )


def total_slots(policy: SchedulePolicy) -> int:
    per_pitch = sum(
        slots_per_pitch(day, policy.match_minutes, policy.break_minutes) for day in policy.days
    )
    return per_pitch * len(set(policy.pitches))
