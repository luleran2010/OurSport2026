"""How teams are ranked into pots and which teams the draw must keep apart."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from engine.rules.base import RuleModel


class SeedingSource(StrEnum):
    PREVIOUS_PLACEMENT = "previous_placement"  # last edition's final placement
    RATING = "rating"  # OurSport rating from other tournaments
    ORGANISER_ORDER = "organiser_order"  # the order the organiser listed the teams in
    NONE = "none"  # unseeded: random among the remaining teams


class Separation(RuleModel):
    """Teams that must be spread across groups.

    `distinct_groups`: every listed team in a different group.
    `max_per_group`: at most `max_per_group` of the listed teams in any one group.
    """

    kind: Literal["distinct_groups", "max_per_group"] = "distinct_groups"
    teams: list[str] = Field(min_length=2)
    max_per_group: int = Field(default=1, ge=1)
    reason: str  # shown to the organiser: "2025 semi-finalists", "same club"


class FixedPlacement(RuleModel):
    team: str
    group_index: int = Field(ge=0)
    position_in_group: int | None = Field(default=None, ge=1)  # draw position, e.g. host = A1


class SeedingPolicy(RuleModel):
    source: list[SeedingSource] = Field(min_length=1)  # priority order; later = fallback
    pots: Literal["by_group_position", "none"] = "by_group_position"
    separations: list[Separation] = Field(default_factory=list)
    fixed: list[FixedPlacement] = Field(default_factory=list)
