"""Futsal: football's results, tables and shootouts, with futsal match rules.

- 2 x 20 minutes (a stopped clock makes a match take about half as long again), 10 minute
  half-time, extra time 2 x 5 minutes, penalties in knockouts.
- Accumulated fouls count per team per half; the second half's carry into extra time.
  From the sixth foul (`foul_limit` + 1) every foul gives a direct free kick: a moment.
- One timeout per team per half, none in extra time.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Self

from pydantic import Field, model_validator

from engine.model import EventLite, LiveStateLite
from engine.rules.base import RuleModel
from engine.rules.config import RuleConfig
from engine.sports.base import InvalidEvent
from engine.sports.football import EVENT_TYPES as FOOTBALL_EVENTS
from engine.sports.football import TEAM_EVENTS as FOOTBALL_TEAM_EVENTS
from engine.sports.football import FootballSport

__all__ = ["EVENT_TYPES", "FUTSAL", "FutsalMatchRules", "FutsalSport", "InvalidEvent"]

EVENT_TYPES = FOOTBALL_EVENTS | {"foul", "timeout"}
TEAM_EVENTS = FOOTBALL_TEAM_EVENTS | {"foul", "timeout"}
STOPPED_CLOCK_FACTOR = 1.5  # a 20 minute half with a stopped clock takes about 30 minutes


class FutsalMatchRules(RuleModel):
    """`RuleConfig.match` for futsal (FIFA Laws of the Game for futsal, community values)."""

    periods: int = Field(default=2, ge=1, le=2)
    period_minutes: int = Field(default=20, ge=5, le=25)
    half_time_minutes: int = Field(default=10, ge=0, le=15)
    stopped_clock: bool = False
    extra_time: bool = False
    extra_time_minutes: int = Field(default=5, ge=1, le=10)
    penalties_in_knockout: bool = True
    squad_size: int = Field(default=5, ge=3, le=5)  # players on court
    rolling_substitutions: bool = True
    foul_limit: int = Field(default=5, ge=1, le=10)  # fouls a half before direct free kicks
    timeouts_per_period: int = Field(default=1, ge=0, le=2)

    @model_validator(mode="after")
    def _halves(self) -> Self:
        if self.periods == 1 and self.half_time_minutes:
            raise ValueError("a one-period game has no half-time")
        return self


class FutsalSport(FootballSport):
    code = "futsal"
    event_types = EVENT_TYPES

    def match_rules(self, match: Mapping[str, Any]) -> FutsalMatchRules:  # type: ignore[override]  # futsal rules extend football's fields
        return FutsalMatchRules.model_validate(match)

    def match_duration_minutes(self, match: Mapping[str, Any]) -> int:
        rules = self.match_rules(match)
        factor = STOPPED_CLOCK_FACTOR if rules.stopped_clock else 1.0
        playing = round(rules.periods * rules.period_minutes * factor)
        return playing + (rules.periods - 1) * rules.half_time_minutes

    def validate_event(
        self,
        state: LiveStateLite,
        event: EventLite,
        rules: RuleConfig,
        *,
        allow_after_full_time: bool = False,
    ) -> None:
        if event.type not in EVENT_TYPES:
            raise InvalidEvent("invalid_event_type", f"'{event.type}' is not a futsal event")
        if event.type not in ("foul", "timeout"):
            super().validate_event(state, event, rules, allow_after_full_time=allow_after_full_time)
            return
        if state.finished and not allow_after_full_time:
            raise InvalidEvent(
                "event_after_full_time", "the match is over; only an admin correction can change it"
            )
        if event.team not in (state.home, state.away):
            raise InvalidEvent("team_not_in_match", "the event's team is not playing this match")
        if event.type == "timeout":
            match_rules = self.match_rules(rules.match)
            if state.period > match_rules.periods:
                raise InvalidEvent(
                    "no_timeout_in_extra_time", "there are no timeouts in extra time"
                )
            taken = state.home_timeouts if event.team == state.home else state.away_timeouts
            if taken >= match_rules.timeouts_per_period:
                raise InvalidEvent("timeout_used", "this team has used its timeout for this half")

    def apply_event(
        self, state: LiveStateLite, event: EventLite, rules: RuleConfig
    ) -> LiveStateLite:
        if event.type == "foul":
            if event.team == state.home:
                return replace(state, home_fouls=state.home_fouls + 1)
            return replace(state, away_fouls=state.away_fouls + 1)
        if event.type == "timeout":
            if event.team == state.home:
                return replace(state, home_timeouts=state.home_timeouts + 1)
            return replace(state, away_timeouts=state.away_timeouts + 1)
        after = super().apply_event(state, event, rules)
        if event.type == "period_start":
            period = int(event.payload["period"])
            regulation = self.match_rules(rules.match).periods
            after = replace(after, home_timeouts=0, away_timeouts=0)
            if period <= regulation:  # extra time keeps the second half's fouls
                after = replace(after, home_fouls=0, away_fouls=0)
        return after

    def detect_moments(
        self,
        before: LiveStateLite,
        after: LiveStateLite,
        event: EventLite,
        rules: RuleConfig | None = None,
    ) -> list[str]:
        if event.type == "timeout":
            return ["timeout"]
        if event.type == "foul":
            match = self.match_rules(rules.match) if rules else FutsalMatchRules()
            fouls = after.home_fouls if event.team == after.home else after.away_fouls
            return ["sixth_foul"] if fouls == match.foul_limit + 1 else []
        return super().detect_moments(before, after, event, rules)


FUTSAL = FutsalSport()
