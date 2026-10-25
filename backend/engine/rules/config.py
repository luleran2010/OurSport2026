"""Tournament rules: points, tiebreakers, advancement and sport-specific match rules.

Extracted by the setup AI or chosen from presets, confirmed by the organiser; the engine
only ever runs a config that `engine.rules.validate` accepts.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from engine.rules.base import RuleModel


class Tiebreaker(StrEnum):
    POINTS = "points"
    POINTS_PER_GAME = "points_per_game"  # comparing across groups of different sizes
    WINS = "wins"
    HEAD_TO_HEAD_POINTS = "head_to_head_points"  # mini-table among the tied teams
    HEAD_TO_HEAD_DIFF = "head_to_head_diff"
    HEAD_TO_HEAD_FOR = "head_to_head_for"
    SCORE_DIFF = "score_diff"  # goal difference
    SCORE_FOR = "score_for"  # goals scored
    AWAY_SCORE_FOR = "away_score_for"
    FAIR_PLAY = "fair_play"  # fewer disciplinary points ranks higher
    DRAW_LOTS = "draw_lots"  # last resort; the engine reports the tie as undecided


HEAD_TO_HEAD = frozenset(
    {Tiebreaker.HEAD_TO_HEAD_POINTS, Tiebreaker.HEAD_TO_HEAD_DIFF, Tiebreaker.HEAD_TO_HEAD_FOR}
)
POINTS_TIEBREAKERS = frozenset({Tiebreaker.POINTS, Tiebreaker.POINTS_PER_GAME})

CompetitionFormat = Literal["round_robin", "double_round_robin", "groups_then_knockout", "knockout"]


class PointsRule(RuleModel):
    table: dict[str, int]  # outcome key -> points; football: {"win": 3, "draw": 1, "loss": 0}


class AdvancementRule(RuleModel):
    per_group: int = Field(ge=0)  # top N of each group advance
    best_of_rest: int = Field(default=0, ge=0)  # e.g. the best 4 third-placed teams
    # How teams from different groups are compared to pick the best of the rest.
    rest_ranking: list[Tiebreaker] = Field(default_factory=list)
    promotion: int = Field(default=0, ge=0)
    relegation: int = Field(default=0, ge=0)


class RuleConfig(RuleModel):
    schema_version: Literal[1] = 1
    sport: str  # a code in engine.sports.registry.SPORTS
    format: CompetitionFormat
    points: PointsRule
    tiebreakers: list[Tiebreaker]  # applied in order
    head_to_head_reapply: bool = True  # re-run h2h among teams still tied after a split
    advancement: AdvancementRule
    standings_visible: bool = True  # False for the youngest age groups that play without tables
    # Sport-specific match rules and walkover score, validated by the sport module.
    match: dict[str, Any] = Field(default_factory=dict)
    walkover: dict[str, Any] = Field(default_factory=dict)
    fair_play_points: dict[str, int] = Field(
        default_factory=lambda: {"yellow": 1, "second_yellow": 3, "red": 3}
    )
