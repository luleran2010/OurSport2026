"""Core input types of the engine (docs/04-engine.md, "Core data types").

Plain frozen dataclasses: the engine receives everything it needs as values and never
looks anything up itself.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from engine.rules.config import RuleConfig
from engine.rules.format import FormatSpec

# A sport-specific result (e.g. `FootballResult`); each sport module defines and interprets
# its own type, so the generic engine treats it as opaque.
type SportResult = object


@dataclass(frozen=True)
class TeamRef:
    id: str
    name: str


@dataclass(frozen=True)
class MatchResult:
    """A finished (or hypothetical) match."""

    match_id: str
    group_id: str | None
    home: str  # team id
    away: str
    outcome: SportResult
    walkover: bool = False
    starts_at: str = ""  # ISO 8601, used only for ordering (form); ties fall back to match_id


@dataclass(frozen=True)
class Fixture:
    """A match not yet played. Knockout teams stay `None` until their source is decided."""

    match_id: str
    group_id: str | None
    home: str | None
    away: str | None
    starts_at: str  # ISO 8601, used only for ordering
    home_source: str | None = None  # "group:A:1", "winner:QF1" (see engine.rules.format)
    away_source: str | None = None


@dataclass(frozen=True)
class TournamentState:
    teams: tuple[TeamRef, ...]
    groups: Mapping[str | None, tuple[str, ...]]  # group id -> team ids
    results: tuple[MatchResult, ...]
    fixtures: tuple[Fixture, ...]
    rules: RuleConfig
    format: FormatSpec
    # Drawing of lots recorded by the organiser, per group: the drawn order of tied teams.
    lots: Mapping[str | None, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class TeamStats:
    """A team's record over a set of results, as the sport module computed it."""

    team: str
    played: int
    won: int
    drawn: int
    lost: int
    outcome_counts: Mapping[str, int]  # per outcome key of the points table
    points: int
    score_for: int
    score_against: int
    away_score_for: int
    fair_play_points: int  # disciplinary points; fewer is better

    @property
    def score_diff(self) -> int:
        return self.score_for - self.score_against


@dataclass(frozen=True)
class EventLite:
    """A match event as the engine sees it: no ids beyond team and player, no timestamps."""

    seq: int
    type: str
    team: str | None = None
    player: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveStateLite:
    """The live state an event is checked against (built by replaying earlier events)."""

    home: str
    away: str
    home_goals: int
    away_goals: int
    period: int  # 0 before kick-off
    knockout: bool = False
    finished: bool = False  # full time reached and the match is decided
    sent_off: frozenset[str] = frozenset()  # player ids
    home_shootout: int = 0  # penalty shootout goals
    away_shootout: int = 0
    home_fouls: int = 0  # accumulated fouls this half (futsal)
    away_fouls: int = 0
    home_timeouts: int = 0  # timeouts taken this period (futsal)
    away_timeouts: int = 0
