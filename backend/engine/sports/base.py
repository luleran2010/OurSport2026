"""The protocols every sport implements (docs/04-engine.md, "Sport modules").

`SportRules` is what configuration validation needs; `SportModule` adds results, team
statistics, scenario outcomes, live events, replay and moments (football and futsal).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from engine.model import EventLite, Fixture, LiveStateLite, MatchResult, SportResult, TeamStats
from engine.rules.config import RuleConfig, Tiebreaker
from engine.rules.issues import Issue


@dataclass(frozen=True)
class MarginAxis:
    """How to vary a result's margin when searching for "win by N" thresholds."""

    unit: str  # "goal_difference"
    max_margin: int
    make: Callable[[int, int], SportResult]  # (home score, away score) -> result


class InvalidEvent(ValueError):
    """An event that cannot happen in the current live state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SportRules(Protocol):
    code: str
    outcome_keys: tuple[str, ...]  # keys of PointsRule.table, best outcome first
    supported_tiebreakers: frozenset[Tiebreaker]
    fair_play_keys: tuple[str, ...]  # keys of RuleConfig.fair_play_points

    def match_rules_issues(self, match: Mapping[str, Any]) -> list[Issue]:
        """Problems with `RuleConfig.match`; paths start with `match.`."""
        ...

    def walkover_issues(self, walkover: Mapping[str, Any]) -> list[Issue]:
        """Problems with `RuleConfig.walkover`; paths start with `walkover.`."""
        ...

    def knockout_issues(self, match: Mapping[str, Any], uses_extra_time: bool) -> list[Issue]:
        """Problems deciding knockout matches under these match rules."""
        ...

    def match_duration_minutes(self, match: Mapping[str, Any]) -> int:
        """Pitch time one match needs under these match rules, breaks included."""
        ...


class SportModule(SportRules, Protocol):
    event_types: frozenset[str]  # what the scorer pad may send

    def outcome_key(self, result: MatchResult, team: str) -> str:
        """The points-table outcome of `result` for `team` (group/league standings)."""
        ...

    def knockout_winner(self, result: MatchResult) -> str:
        """The team that goes through; raises ValueError if the result has no winner."""
        ...

    def team_stats(
        self, results: Sequence[MatchResult], team: str, rules: RuleConfig
    ) -> TeamStats: ...

    def metric(self, tiebreaker: Tiebreaker, stats: TeamStats) -> float | None:
        """Higher ranks higher; None for tiebreakers computed elsewhere (head-to-head, lots)."""
        ...

    def hypothetical_outcomes(
        self, fixture: Fixture, rules: RuleConfig, *, knockout: bool
    ) -> Sequence[SportResult]:
        """One representative result per distinct outcome, for scenario enumeration."""
        ...

    def margin_axis(self) -> MarginAxis: ...

    def walkover_result(
        self, rules: RuleConfig, winner: Literal["home", "away"]
    ) -> SportResult: ...

    def validate_event(
        self,
        state: LiveStateLite,
        event: EventLite,
        rules: RuleConfig,
        *,
        allow_after_full_time: bool = False,
    ) -> None:
        """Raise `InvalidEvent` if `event` cannot happen in `state`."""
        ...

    def replay(
        self,
        home: str,
        away: str,
        events: Sequence[EventLite],
        rules: RuleConfig,
        *,
        knockout: bool = False,
    ) -> LiveStateLite:
        """The live state from every event in order; undone events are skipped."""
        ...

    def result_of(self, state: LiveStateLite, rules: RuleConfig) -> SportResult:
        """The final result a finished live state stands for."""
        ...

    def detect_moments(
        self,
        before: LiveStateLite,
        after: LiveStateLite,
        event: EventLite,
        rules: RuleConfig | None = None,
    ) -> list[str]:
        """What a fan would call a moment (goal, equaliser, red card, …)."""
        ...
