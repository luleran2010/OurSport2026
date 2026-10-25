"""The policy catalogue: fair, internationally used defaults (docs/12-tournament-setup.md §3).

When a rulebook is silent, the setup AI may only pick an id from `PRESETS`; the app then
calls the matching builder here. The catalogue is versioned so every published tournament
records which defaults it used.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from types import MappingProxyType
from typing import Any

from engine.rules.config import (
    AdvancementRule,
    CompetitionFormat,
    PointsRule,
    RuleConfig,
    Tiebreaker,
)
from engine.rules.format import FormatChoice, FormatSpec, groups_then_knockout, league
from engine.rules.schedule_policy import DayWindow, SchedulePolicy
from engine.rules.seeding import SeedingPolicy, SeedingSource, Separation
from engine.sports.base import SportRules
from engine.sports.football import FOOTBALL, FootballMatchRules, FootballWalkover
from engine.sports.futsal import FUTSAL, FutsalMatchRules

CATALOGUE_VERSION = 3  # 2: format_auto; 3: futsal presets


class PresetKind(StrEnum):
    TIEBREAKERS = "tiebreakers"
    FORMAT = "format"
    SEEDING = "seeding"
    SCHEDULE = "schedule"


@dataclass(frozen=True)
class Preset:
    id: str
    kind: PresetKind
    summary: str  # plain language, shown to organisers and given to the setup AI
    practice: str  # where this practice comes from


def _presets(*presets: Preset) -> Mapping[str, Preset]:
    return MappingProxyType({preset.id: preset for preset in presets})


PRESETS = _presets(
    Preset(
        "football_gd_first",
        PresetKind.TIEBREAKERS,
        "Ties on points are broken by goal difference, then goals scored, then the matches "
        "between the tied teams, then fair play, then drawing lots.",
        "Most national leagues",
    ),
    Preset(
        "football_h2h_first",
        PresetKind.TIEBREAKERS,
        "Ties on points are broken by the matches between the tied teams first, then goal "
        "difference, goals scored, fair play and drawing lots.",
        "UEFA tournaments (group stages)",
    ),
    Preset(
        "futsal_gd_first",
        PresetKind.TIEBREAKERS,
        "Futsal: ties on points are broken by goal difference, then goals scored, then the "
        "matches between the tied teams, then fair play, then drawing lots.",
        "Futsal leagues",
    ),
    Preset(
        "futsal_h2h_first",
        PresetKind.TIEBREAKERS,
        "Futsal: ties on points are broken by the matches between the tied teams first, then "
        "goal difference, goals scored, fair play and drawing lots.",
        "FIFA futsal tournaments",
    ),
    Preset(
        "format_groups_of_4_sf",
        PresetKind.FORMAT,
        "8 teams: 2 groups of 4, top 2 to the semi-finals, third-place match and final.",
        "Youth and community cups",
    ),
    Preset(
        "format_groups_of_4_qf",
        PresetKind.FORMAT,
        "16 teams: 4 groups of 4, top 2 to the quarter-finals, then semi-finals, "
        "third-place match and final.",
        "FIFA/UEFA-style tournaments",
    ),
    Preset(
        "format_groups_of_4_r16_best_thirds",
        PresetKind.FORMAT,
        "24 teams: 6 groups of 4, top 2 and the 4 best third-placed teams to the round of 16.",
        "UEFA European Championship (24 teams)",
    ),
    Preset(
        "format_groups_of_4_r16",
        PresetKind.FORMAT,
        "32 teams: 8 groups of 4, top 2 to the round of 16.",
        "FIFA World Cup (32 teams)",
    ),
    Preset(
        "format_league",
        PresetKind.FORMAT,
        "Everyone plays everyone once; the table decides.",
        "Leagues and round-robin tournaments",
    ),
    Preset(
        "format_league_double",
        PresetKind.FORMAT,
        "Everyone plays everyone twice (home and away); the table decides.",
        "National leagues",
    ),
    Preset(
        "format_auto",
        PresetKind.FORMAT,
        "Any number of teams: the formats that fit the days and pitches, ranked: groups of 4 "
        "where possible, everyone plays at least 3 matches, a knockout to finish.",
        "FIFA/UEFA-style group stages, adapted to the time available",
    ),
    Preset(
        "seeding_previous_placement",
        PresetKind.SEEDING,
        "Teams are put in pots by last year's final placement (then rating, then unseeded); "
        "last year's semi-finalists (quarter-finalists with 8+ groups) go to different groups.",
        "UEFA/FIFA pot seeding",
    ),
    Preset(
        "separation_same_organisation",
        PresetKind.SEEDING,
        "Teams from the same club or organisation go to different groups whenever possible.",
        "UEFA country protection",
    ),
    Preset(
        "schedule_community_weekend",
        PresetKind.SCHEDULE,
        "5 minutes between matches on a pitch, at least one free slot (and an hour for longer "
        "matches) between a team's games, at most 3 games per team per day; the last group "
        "round kicks off at the same time.",
        "Youth and community tournament guidelines; FIFA simultaneous final group matches",
    ),
    Preset(
        "schedule_junior",
        PresetKind.SCHEDULE,
        "As the community weekend, but at most 2 games per team per day and at least an hour "
        "of rest between games.",
        "Junior tournament guidelines (U12 and younger)",
    ),
)


# --- tiebreakers and rules -------------------------------------------------------------------

_GD_FIRST = (
    Tiebreaker.POINTS,
    Tiebreaker.SCORE_DIFF,
    Tiebreaker.SCORE_FOR,
    Tiebreaker.HEAD_TO_HEAD_POINTS,
    Tiebreaker.HEAD_TO_HEAD_DIFF,
    Tiebreaker.FAIR_PLAY,
    Tiebreaker.DRAW_LOTS,
)
_H2H_FIRST = (
    Tiebreaker.POINTS,
    Tiebreaker.HEAD_TO_HEAD_POINTS,
    Tiebreaker.HEAD_TO_HEAD_DIFF,
    Tiebreaker.HEAD_TO_HEAD_FOR,
    Tiebreaker.SCORE_DIFF,
    Tiebreaker.SCORE_FOR,
    Tiebreaker.FAIR_PLAY,
    Tiebreaker.DRAW_LOTS,
)
# Futsal tables break ties the same ways (FIFA futsal regulations use the same steps).
TIEBREAKER_PRESETS: Mapping[str, tuple[Tiebreaker, ...]] = MappingProxyType(
    {
        "football_gd_first": _GD_FIRST,
        "football_h2h_first": _H2H_FIRST,
        "futsal_gd_first": _GD_FIRST,
        "futsal_h2h_first": _H2H_FIRST,
    }
)

# Teams from different groups never met, so head-to-head steps are left out.
_REST_RANKING = (
    Tiebreaker.SCORE_DIFF,
    Tiebreaker.SCORE_FOR,
    Tiebreaker.FAIR_PLAY,
    Tiebreaker.DRAW_LOTS,
)


def football_match_rules(**overrides: Any) -> dict[str, Any]:
    """Football match rules for a community tournament (2 x 20 min, 5 min half-time)."""
    values: dict[str, Any] = {"periods": 2, "period_minutes": 20, "half_time_minutes": 5}
    values.update(overrides)
    return FootballMatchRules.model_validate(values).model_dump()


def futsal_match_rules(**overrides: Any) -> dict[str, Any]:
    """Futsal match rules (2 x 20 min running clock, 10 min half-time, 5 fouls a half)."""
    return FutsalMatchRules.model_validate(overrides).model_dump()


def match_rules_for(sport: str, **overrides: Any) -> dict[str, Any]:
    """Community defaults of a sport's match rules."""
    if sport == FUTSAL.code:
        return futsal_match_rules(**overrides)
    return football_match_rules(**overrides)


def _competition_format(fmt: FormatSpec) -> CompetitionFormat:
    if fmt.knockout is not None:
        return "groups_then_knockout" if fmt.group_sizes else "knockout"
    return "double_round_robin" if fmt.group_rounds == 2 else "round_robin"


def _with_rest_ranking(fmt: FormatSpec, advancement: AdvancementRule) -> AdvancementRule:
    if advancement.best_of_rest == 0 or advancement.rest_ranking:
        return advancement
    first = Tiebreaker.POINTS_PER_GAME if len(set(fmt.group_sizes)) > 1 else Tiebreaker.POINTS
    return advancement.model_copy(update={"rest_ranking": [first, *_REST_RANKING]})


def football_rules(
    tiebreakers_preset: str,
    choice: FormatChoice,
    *,
    match: Mapping[str, Any] | None = None,
    walkover: Mapping[str, Any] | None = None,
) -> RuleConfig:
    """A complete football RuleConfig from a tiebreaker preset and a format choice."""
    return RuleConfig(
        sport=FOOTBALL.code,
        format=_competition_format(choice.format),
        points=PointsRule(table={"win": 3, "draw": 1, "loss": 0}),
        tiebreakers=list(TIEBREAKER_PRESETS[tiebreakers_preset]),
        advancement=_with_rest_ranking(choice.format, choice.advancement),
        match=dict(match) if match is not None else football_match_rules(),
        walkover=dict(walkover) if walkover is not None else FootballWalkover().model_dump(),
    )


def futsal_rules(
    tiebreakers_preset: str,
    choice: FormatChoice,
    *,
    match: Mapping[str, Any] | None = None,
    walkover: Mapping[str, Any] | None = None,
) -> RuleConfig:
    """A complete futsal RuleConfig: football's points and tables, futsal match rules."""
    rules = football_rules(
        tiebreakers_preset, choice, match=match or futsal_match_rules(), walkover=walkover
    )
    return rules.model_copy(update={"sport": FUTSAL.code})


def sport_rules(
    sport: str,
    tiebreakers_preset: str,
    choice: FormatChoice,
    *,
    match: Mapping[str, Any] | None = None,
    walkover: Mapping[str, Any] | None = None,
) -> RuleConfig:
    """The RuleConfig of any goal-based sport in the registry (football, futsal)."""
    build = futsal_rules if sport == FUTSAL.code else football_rules
    return build(tiebreakers_preset, choice, match=match, walkover=walkover)


def preset_for(sport: str, order: str = "h2h_first") -> str:
    """The tiebreaker preset id of a sport (`h2h_first` or `gd_first`)."""
    return f"{FUTSAL.code if sport == FUTSAL.code else 'football'}_{order}"


# --- formats ---------------------------------------------------------------------------------


def _fixed_groups(
    group_count: int, *, per_group: int = 2, best_of_rest: int = 0, third_place: bool = True
) -> Callable[[int | None], FormatChoice]:
    def build(team_count: int | None) -> FormatChoice:
        if team_count is not None and team_count != group_count * 4:
            raise ValueError(f"this format is for {group_count * 4} teams, not {team_count}")
        return groups_then_knockout(
            [4] * group_count,
            per_group=per_group,
            best_of_rest=best_of_rest,
            third_place_match=third_place,
        )

    return build


def _league(*, double: bool) -> Callable[[int | None], FormatChoice]:
    def build(team_count: int | None) -> FormatChoice:
        if team_count is None:
            raise ValueError("a league needs the number of teams")
        return league(team_count, double=double)

    return build


FORMAT_PRESETS: Mapping[str, Callable[[int | None], FormatChoice]] = MappingProxyType(
    {
        "format_groups_of_4_sf": _fixed_groups(2),
        "format_groups_of_4_qf": _fixed_groups(4),
        "format_groups_of_4_r16_best_thirds": _fixed_groups(6, best_of_rest=4, third_place=False),
        "format_groups_of_4_r16": _fixed_groups(8, third_place=False),
        "format_league": _league(double=False),
        "format_league_double": _league(double=True),
    }
)


# --- seeding ---------------------------------------------------------------------------------


def _spread(teams: Sequence[str], group_count: int, reason: str) -> Separation:
    """Keep `teams` apart: one per group if they fit, otherwise as evenly as possible."""
    if len(teams) <= group_count:
        return Separation(teams=list(teams), reason=reason)
    return Separation(
        kind="max_per_group",
        teams=list(teams),
        max_per_group=ceil(len(teams) / group_count),
        reason=reason,
    )


def seeding_previous_placement(
    *,
    group_count: int,
    previous_semi_finalists: Sequence[str] = (),
    previous_quarter_finalists: Sequence[str] = (),
) -> SeedingPolicy:
    protected, reason = previous_semi_finalists, "last edition's semi-finalists"
    if group_count >= 8 and previous_quarter_finalists:
        protected, reason = previous_quarter_finalists, "last edition's quarter-finalists"
    separations = [_spread(protected, group_count, reason)] if len(protected) >= 2 else []
    return SeedingPolicy(
        source=[SeedingSource.PREVIOUS_PLACEMENT, SeedingSource.RATING, SeedingSource.NONE],
        pots="by_group_position",
        separations=separations,
    )


def separation_same_organisation(
    teams_by_organisation: Mapping[str, Sequence[str]], *, group_count: int
) -> list[Separation]:
    return [
        _spread(teams, group_count, "same organisation")
        for _, teams in sorted(teams_by_organisation.items())
        if len(teams) >= 2
    ]


# --- schedule --------------------------------------------------------------------------------

_CHANGEOVER_MINUTES = 5
_LONG_MATCH_MINUTES = 40
_LONG_MATCH_REST_MINUTES = 60


def _schedule(
    days: Sequence[DayWindow],
    pitches: Sequence[str],
    match: Mapping[str, Any],
    *,
    sport: SportRules,
    time_zone: str,
    max_per_day: int,
    min_rest_floor: int,
) -> SchedulePolicy:
    duration = sport.match_duration_minutes(match)
    one_slot = duration + _CHANGEOVER_MINUTES
    long_match_rest = _LONG_MATCH_REST_MINUTES if duration >= _LONG_MATCH_MINUTES else 0
    return SchedulePolicy(
        time_zone=time_zone,
        days=list(days),
        pitches=list(pitches),
        match_minutes=duration,
        break_minutes=_CHANGEOVER_MINUTES,
        min_rest_minutes=max(one_slot, long_match_rest, min_rest_floor),
        max_matches_per_team_per_day=max_per_day,
        simultaneous_last_group_round=True,
    )


def schedule_community_weekend(
    days: Sequence[DayWindow],
    pitches: Sequence[str],
    match: Mapping[str, Any],
    *,
    sport: SportRules = FOOTBALL,
    time_zone: str = "Europe/Helsinki",
) -> SchedulePolicy:
    # One-day futsal cups play group, semi-final and final on the same day (short games).
    max_per_day = 5 if sport.code == FUTSAL.code else 3
    return _schedule(
        days,
        pitches,
        match,
        sport=sport,
        time_zone=time_zone,
        max_per_day=max_per_day,
        min_rest_floor=0,
    )


def schedule_junior(
    days: Sequence[DayWindow],
    pitches: Sequence[str],
    match: Mapping[str, Any],
    *,
    sport: SportRules = FOOTBALL,
    time_zone: str = "Europe/Helsinki",
) -> SchedulePolicy:
    return _schedule(
        days,
        pitches,
        match,
        sport=sport,
        time_zone=time_zone,
        max_per_day=2,
        min_rest_floor=_LONG_MATCH_REST_MINUTES,
    )
