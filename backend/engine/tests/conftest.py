import datetime as dt
from typing import Any

import pytest

from engine.rules.config import AdvancementRule, PointsRule, RuleConfig, Tiebreaker
from engine.rules.schedule_policy import DayWindow, SchedulePolicy

HELSINKI_SUMMER_OFFSET = 180


def make_rules(**overrides: Any) -> RuleConfig:
    """A valid football group-stage-then-knockout config, with field overrides."""
    values: dict[str, Any] = {
        "sport": "football",
        "format": "groups_then_knockout",
        "points": PointsRule(table={"win": 3, "draw": 1, "loss": 0}),
        "tiebreakers": [
            Tiebreaker.POINTS,
            Tiebreaker.SCORE_DIFF,
            Tiebreaker.SCORE_FOR,
            Tiebreaker.HEAD_TO_HEAD_POINTS,
            Tiebreaker.FAIR_PLAY,
            Tiebreaker.DRAW_LOTS,
        ],
        "advancement": AdvancementRule(per_group=2),
        "match": {"periods": 2, "period_minutes": 20, "half_time_minutes": 5},
        "walkover": {"score_for": 3, "score_against": 0},
    }
    values.update(overrides)
    return RuleConfig(**values)


def make_day(day: int, start: str = "09:00", end: str = "19:00", **overrides: Any) -> DayWindow:
    values: dict[str, Any] = {
        "date": dt.date(2026, 6, day),
        "start": dt.time.fromisoformat(start),
        "end": dt.time.fromisoformat(end),
        "utc_offset_minutes": HELSINKI_SUMMER_OFFSET,
    }
    values.update(overrides)
    return DayWindow(**values)


def make_schedule(**overrides: Any) -> SchedulePolicy:
    """Three tournament days on four pitches, 45-minute matches with 5-minute breaks."""
    values: dict[str, Any] = {
        "time_zone": "Europe/Helsinki",
        "days": [make_day(12), make_day(13), make_day(14)],
        "pitches": ["p1", "p2", "p3", "p4"],
        "match_minutes": 45,
        "break_minutes": 5,
        "min_rest_minutes": 60,
        "max_matches_per_team_per_day": 3,
    }
    values.update(overrides)
    return SchedulePolicy(**values)


@pytest.fixture
def team_ids() -> list[str]:
    return [f"t{i:02d}" for i in range(1, 17)]
