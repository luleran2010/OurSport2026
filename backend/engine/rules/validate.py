"""Semantic validation of tournament configurations.

Pydantic already rejects wrong types and ranges when a model is built. These checks find
problems that need the whole picture (sport, format, teams, calendar). Every check returns
all issues it finds so the organiser can fix them in one pass.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from engine.rules.config import HEAD_TO_HEAD, POINTS_TIEBREAKERS, RuleConfig, Tiebreaker
from engine.rules.format import (
    MAX_GROUPS,
    ROUND_ORDER,
    ROUND_SIZE,
    FormatSpec,
    all_match_codes,
    first_round_for,
    max_matches_per_team,
    qualifier_sources,
    round_label,
    total_match_count,
)
from engine.rules.issues import InvalidConfig, Issue
from engine.rules.schedule_policy import (
    SchedulePolicy,
    free_segments,
    minute_of_day,
    total_slots,
)
from engine.rules.seeding import SeedingPolicy, SeedingSource
from engine.sports.base import SportRules
from engine.sports.registry import SPORTS


def ensure_valid(issues: Sequence[Issue]) -> None:
    """Raise `InvalidConfig` carrying every issue, if there are any."""
    if issues:
        raise InvalidConfig(issues)


def validate_setup(
    rules: RuleConfig,
    fmt: FormatSpec,
    seeding: SeedingPolicy | None = None,
    schedule: SchedulePolicy | None = None,
    team_ids: Sequence[str] | None = None,
    *,
    sports: Mapping[str, SportRules] = SPORTS,
) -> list[Issue]:
    """Validate everything the setup produces, as one list of issues."""
    issues = validate_rule_config(rules, sports=sports)
    issues += validate_format(fmt, rules, sports=sports)
    if seeding is not None:
        issues += validate_seeding(seeding, fmt, team_ids or [])
    if schedule is not None:
        issues += validate_schedule(schedule, fmt, rules, sports=sports)
    return issues


# --- rules -----------------------------------------------------------------------------------


def validate_rule_config(
    rules: RuleConfig, *, sports: Mapping[str, SportRules] = SPORTS
) -> list[Issue]:
    sport = sports.get(rules.sport)
    if sport is None:
        known = ", ".join(sorted(sports))
        return [
            Issue(
                "unknown_sport",
                "sport",
                f"'{rules.sport}' is not a supported sport; supported: {known}",
            )
        ]

    issues = _points_issues(rules, sport)
    issues += _tiebreaker_issues(rules.tiebreakers, sport, "tiebreakers", require_points=True)
    issues += _advancement_issues(rules, sport)
    issues += sport.match_rules_issues(rules.match)
    issues += sport.walkover_issues(rules.walkover)
    for key in rules.fair_play_points:
        if key not in sport.fair_play_keys:
            expected = ", ".join(sport.fair_play_keys) or "none"
            issues.append(
                Issue(
                    "unknown_fair_play_key",
                    f"fair_play_points.{key}",
                    f"'{key}' is not a disciplinary event in {sport.code}; expected: {expected}",
                )
            )
        elif rules.fair_play_points[key] < 0:
            issues.append(
                Issue(
                    "invalid_fair_play_points",
                    f"fair_play_points.{key}",
                    "fair-play points cannot be negative",
                )
            )
    return issues


def _points_issues(rules: RuleConfig, sport: SportRules) -> list[Issue]:
    table = rules.points.table
    expected = ", ".join(sport.outcome_keys)
    issues = [
        Issue(
            "unknown_outcome_key",
            f"points.table.{key}",
            f"'{key}' is not an outcome in {sport.code}; expected one of: {expected}",
        )
        for key in table
        if key not in sport.outcome_keys
    ]
    issues += [
        Issue(
            "missing_outcome_key",
            f"points.table.{key}",
            f"no points given for the outcome '{key}'",
        )
        for key in sport.outcome_keys
        if key not in table
    ]
    issues += [
        Issue("invalid_points", f"points.table.{key}", "points cannot be negative")
        for key, value in table.items()
        if value < 0
    ]
    best, worst = sport.outcome_keys[0], sport.outcome_keys[-1]
    if best in table and worst in table and table[best] <= table[worst]:
        issues.append(
            Issue(
                "invalid_points",
                f"points.table.{best}",
                f"a {best} must be worth more points than a {worst}",
            )
        )
    return issues


def _tiebreaker_issues(
    tiebreakers: Sequence[Tiebreaker], sport: SportRules, path: str, *, require_points: bool
) -> list[Issue]:
    issues: list[Issue] = []
    if require_points and (not tiebreakers or tiebreakers[0] not in POINTS_TIEBREAKERS):
        issues.append(
            Issue(
                "tiebreaker_order",
                f"{path}[0]",
                "teams are ranked by points first; start the list with points",
            )
        )
    seen: set[Tiebreaker] = set()
    for index, tiebreaker in enumerate(tiebreakers):
        where = f"{path}[{index}]"
        if tiebreaker not in sport.supported_tiebreakers:
            issues.append(
                Issue(
                    "tiebreaker_not_supported",
                    where,
                    f"{tiebreaker.value} is not a tiebreaker in {sport.code}",
                )
            )
        if tiebreaker in seen:
            issues.append(
                Issue("tiebreaker_duplicate", where, f"{tiebreaker.value} is listed twice")
            )
        seen.add(tiebreaker)
        if tiebreaker is Tiebreaker.DRAW_LOTS and index != len(tiebreakers) - 1:
            issues.append(
                Issue(
                    "draw_lots_not_last",
                    where,
                    "drawing lots is the last resort and must come last",
                )
            )
    return issues


def _advancement_issues(rules: RuleConfig, sport: SportRules) -> list[Issue]:
    advancement = rules.advancement
    if advancement.best_of_rest == 0:
        return []
    if not advancement.rest_ranking:
        return [
            Issue(
                "rest_ranking_missing",
                "advancement.rest_ranking",
                "say how teams from different groups are compared "
                f"to pick the best {advancement.best_of_rest}",
            )
        ]
    issues = _tiebreaker_issues(
        advancement.rest_ranking, sport, "advancement.rest_ranking", require_points=True
    )
    issues += [
        Issue(
            "tiebreaker_not_applicable",
            f"advancement.rest_ranking[{index}]",
            f"{tiebreaker.value} cannot rank teams from different groups "
            "(they have not played each other)",
        )
        for index, tiebreaker in enumerate(advancement.rest_ranking)
        if tiebreaker in HEAD_TO_HEAD
    ]
    return issues


# --- format ----------------------------------------------------------------------------------


def validate_format(
    fmt: FormatSpec, rules: RuleConfig, *, sports: Mapping[str, SportRules] = SPORTS
) -> list[Issue]:
    if fmt.group_count > MAX_GROUPS:
        # Groups are lettered A-Z; nothing else can be checked meaningfully.
        return [Issue("too_many_groups", "format.group_sizes", f"at most {MAX_GROUPS} groups")]
    issues = _format_shape_issues(fmt, rules)
    if fmt.group_sizes:
        issues += _group_advancement_issues(fmt, rules)
    if fmt.knockout is not None:
        issues += _knockout_issues(fmt, rules, sports)
    return issues


def _format_shape_issues(fmt: FormatSpec, rules: RuleConfig) -> list[Issue]:
    issues: list[Issue] = []
    has_groups, has_knockout = bool(fmt.group_sizes), fmt.knockout is not None
    expected = {
        "round_robin": (True, False, fmt.group_count == 1 and fmt.group_rounds == 1),
        "double_round_robin": (True, False, fmt.group_count == 1 and fmt.group_rounds == 2),
        "groups_then_knockout": (True, True, True),
        "knockout": (False, True, True),
    }[rules.format]
    if (has_groups, has_knockout) != expected[:2] or not expected[2]:
        issues.append(
            Issue(
                "format_mismatch",
                "format",
                f"the rules say '{rules.format.replace('_', ' ')}', but the structure has "
                f"{fmt.group_count} group(s) x {fmt.group_rounds} round(s) and "
                f"{'a' if has_knockout else 'no'} knockout",
            )
        )
    for index, size in enumerate(fmt.group_sizes):
        if size < 2:
            issues.append(
                Issue(
                    "group_too_small",
                    f"format.group_sizes[{index}]",
                    "a group needs at least 2 teams",
                )
            )
    if has_groups and sum(fmt.group_sizes) != fmt.team_count:
        issues.append(
            Issue(
                "team_count_mismatch",
                "format.team_count",
                f"the groups hold {sum(fmt.group_sizes)} teams, but there are {fmt.team_count}",
            )
        )
    return issues


def _group_advancement_issues(fmt: FormatSpec, rules: RuleConfig) -> list[Issue]:
    issues: list[Issue] = []
    advancement = rules.advancement
    smallest = min(fmt.group_sizes)
    if advancement.per_group > smallest:
        issues.append(
            Issue(
                "advancement_exceeds_group",
                "advancement.per_group",
                f"top {advancement.per_group} cannot advance from a group of {smallest}",
            )
        )
    if advancement.best_of_rest:
        groups_with_rest = sum(size > advancement.per_group for size in fmt.group_sizes)
        if advancement.best_of_rest > groups_with_rest:
            issues.append(
                Issue(
                    "best_of_rest_too_many",
                    "advancement.best_of_rest",
                    f"best {advancement.best_of_rest} of the rest needs at least that many "
                    f"groups with teams left over, but there are {groups_with_rest}",
                )
            )
        if len(set(fmt.group_sizes)) > 1 and (
            not advancement.rest_ranking
            or advancement.rest_ranking[0] is not Tiebreaker.POINTS_PER_GAME
        ):
            issues.append(
                Issue(
                    "rest_ranking_unequal_groups",
                    "advancement.rest_ranking[0]",
                    "groups have different sizes, so teams from different groups must be "
                    "compared by points per game first",
                )
            )
    return issues


def _knockout_issues(
    fmt: FormatSpec, rules: RuleConfig, sports: Mapping[str, SportRules]
) -> list[Issue]:
    assert fmt.knockout is not None
    knockout = fmt.knockout
    issues: list[Issue] = []

    expected_rounds = list(ROUND_ORDER[ROUND_ORDER.index(knockout.rounds[0]) :])
    if knockout.rounds != expected_rounds:
        issues.append(
            Issue(
                "knockout_rounds_invalid",
                "format.knockout.rounds",
                "knockout rounds must follow each other without gaps and end with the final: "
                + " -> ".join(round_label(r) for r in expected_rounds),
            )
        )
    if knockout.third_place_match and "semi_final" not in knockout.rounds:
        issues.append(
            Issue(
                "third_place_needs_semi_final",
                "format.knockout.third_place_match",
                "a third-place match is played by the semi-final losers, "
                "so the knockout needs semi-finals",
            )
        )

    bracket = ROUND_SIZE[knockout.rounds[0]]
    qualifiers = qualifier_sources(fmt, rules.advancement)
    if fmt.group_sizes and len(qualifiers) != bracket:
        advancement = rules.advancement
        made_of = f"{fmt.group_count} groups x top {advancement.per_group}"
        if advancement.best_of_rest:
            made_of += f" + best {advancement.best_of_rest}"
        issues.append(
            Issue(
                "advancement_bracket_mismatch",
                "advancement.per_group",
                f"{made_of} = {len(qualifiers)} qualifiers, but a bracket starting at the "
                f"{round_label(knockout.rounds[0])} takes {bracket}",
            )
        )
    if not fmt.group_sizes and first_round_for(fmt.team_count) != knockout.rounds[0]:
        issues.append(
            Issue(
                "knockout_size_not_supported",
                "format.team_count",
                f"a knockout of {fmt.team_count} teams starting at the "
                f"{round_label(knockout.rounds[0])} would need byes, which are not supported yet",
            )
        )
    if knockout.crossover == "custom":
        issues += _custom_pair_issues(fmt, qualifiers, bracket)

    sport = sports.get(rules.sport)
    if sport is not None:
        uses_extra_time = "extra_time_then_penalties" in (
            knockout.draws_decided_by,
            knockout.final_draws_decided_by,
        )
        issues += sport.knockout_issues(rules.match, uses_extra_time)
    return issues


def _custom_pair_issues(fmt: FormatSpec, qualifiers: list[str], bracket: int) -> list[Issue]:
    assert fmt.knockout is not None
    pairs = fmt.knockout.custom_pairs
    issues: list[Issue] = []
    used = [source for pair in pairs for source in pair]
    unknown = sorted(set(used) - set(qualifiers))
    if unknown:
        issues.append(
            Issue(
                "custom_pairs_invalid",
                "format.knockout.custom_pairs",
                f"these are not qualifiers of this format: {', '.join(unknown)}",
            )
        )
    counts = Counter(used)
    missing = [q for q in qualifiers if counts[q] == 0]
    repeated = sorted(source for source, count in counts.items() if count > 1)
    if len(pairs) != bracket // 2 or missing or repeated:
        details = [f"{len(pairs)} pairs for {bracket // 2} first-round matches"]
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if repeated:
            details.append(f"repeated: {', '.join(repeated)}")
        issues.append(
            Issue(
                "custom_pairs_invalid",
                "format.knockout.custom_pairs",
                "every qualifier must appear in exactly one first-round pair ("
                + "; ".join(details)
                + ")",
            )
        )
    return issues


# --- seeding ---------------------------------------------------------------------------------


def validate_seeding(
    policy: SeedingPolicy, fmt: FormatSpec, team_ids: Sequence[str]
) -> list[Issue]:
    issues: list[Issue] = []
    known = set(team_ids)
    groups = fmt.group_count

    if SeedingSource.NONE in policy.source[:-1] or len(set(policy.source)) != len(policy.source):
        issues.append(
            Issue(
                "seeding_source_invalid",
                "seeding.source",
                "list each seeding source once, with 'none' (unseeded) only as the last fallback",
            )
        )
    if groups == 0:
        if policy.pots != "none" or policy.separations or policy.fixed:
            issues.append(
                Issue(
                    "pots_need_groups",
                    "seeding.pots",
                    "pots, separations and fixed placements apply to a group draw, "
                    "but this format has no groups",
                )
            )
        return issues

    for index, separation in enumerate(policy.separations):
        path = f"seeding.separations[{index}]"
        for team_index, team in enumerate(separation.teams):
            if team not in known:
                issues.append(
                    Issue(
                        "separation_unknown_team",
                        f"{path}.teams[{team_index}]",
                        f"'{team}' is not one of the tournament's teams",
                    )
                )
        capacity = groups * (
            1 if separation.kind == "distinct_groups" else separation.max_per_group
        )
        if len(set(separation.teams)) > capacity:
            rule = (
                "must be in different groups"
                if separation.kind == "distinct_groups"
                else f"may have at most {separation.max_per_group} per group"
            )
            issues.append(
                Issue(
                    "separation_unsatisfiable",
                    path,
                    f"{len(set(separation.teams))} teams ({separation.reason}) {rule}, "
                    f"but there are only {groups} groups",
                )
            )

    issues += _fixed_placement_issues(policy, fmt, known)
    return issues


def _fixed_placement_issues(policy: SeedingPolicy, fmt: FormatSpec, known: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    group_of: dict[str, int] = {}
    taken_positions: set[tuple[int, int]] = set()
    per_group: Counter[int] = Counter()
    for index, fixed in enumerate(policy.fixed):
        path = f"seeding.fixed[{index}]"
        problem = None
        if fixed.team not in known:
            problem = f"'{fixed.team}' is not one of the tournament's teams"
        elif fixed.team in group_of:
            problem = f"'{fixed.team}' is placed more than once"
        elif fixed.group_index >= fmt.group_count:
            problem = f"group {fixed.group_index + 1} does not exist ({fmt.group_count} groups)"
        elif fixed.position_in_group is not None and (
            fixed.position_in_group > fmt.group_sizes[fixed.group_index]
            or (fixed.group_index, fixed.position_in_group) in taken_positions
        ):
            problem = f"position {fixed.position_in_group} is not free in that group"
        elif per_group[fixed.group_index] >= fmt.group_sizes[fixed.group_index]:
            problem = "that group is already full of fixed teams"
        if problem:
            issues.append(Issue("fixed_placement_invalid", path, problem))
            continue
        group_of[fixed.team] = fixed.group_index
        per_group[fixed.group_index] += 1
        if fixed.position_in_group is not None:
            taken_positions.add((fixed.group_index, fixed.position_in_group))

    for index, separation in enumerate(policy.separations):
        limit = 1 if separation.kind == "distinct_groups" else separation.max_per_group
        fixed_counts = Counter(group_of[t] for t in separation.teams if t in group_of)
        for group_index, count in fixed_counts.items():
            if count > limit:
                issues.append(
                    Issue(
                        "fixed_conflicts_separation",
                        f"seeding.separations[{index}]",
                        f"fixed placements put {count} teams ({separation.reason}) in group "
                        f"{group_index + 1}, which this separation forbids",
                    )
                )
    return issues


# --- schedule --------------------------------------------------------------------------------


def validate_schedule(
    policy: SchedulePolicy,
    fmt: FormatSpec,
    rules: RuleConfig | None = None,
    *,
    sports: Mapping[str, SportRules] = SPORTS,
) -> list[Issue]:
    issues = _calendar_issues(policy)

    if len(set(policy.pitches)) != len(policy.pitches):
        issues.append(
            Issue("schedule_pitches_invalid", "schedule.pitches", "each pitch must be listed once")
        )

    sport = sports.get(rules.sport) if rules is not None else None
    if rules is not None and sport is not None and not sport.match_rules_issues(rules.match):
        needed = sport.match_duration_minutes(rules.match)
        if policy.match_minutes < needed:
            issues.append(
                Issue(
                    "match_too_short_for_rules",
                    "schedule.match_minutes",
                    f"{policy.match_minutes} minutes per match is shorter than a match "
                    f"under these rules ({needed} minutes including breaks)",
                )
            )

    matches, slots = total_match_count(fmt), total_slots(policy)
    if slots < matches:
        issues.append(
            Issue(
                "schedule_too_few_slots",
                "schedule",
                f"{matches} matches need {matches} slots, but the days and pitches give {slots}",
            )
        )
    last_round = max((size // 2 for size in fmt.group_sizes), default=0)
    if policy.simultaneous_last_group_round and last_round > len(set(policy.pitches)):
        issues.append(
            Issue(
                "schedule_last_round_needs_pitches",
                "schedule.simultaneous_last_group_round",
                f"the last group round kicks off together: {last_round} matches need "
                f"{last_round} pitches, but there are {len(set(policy.pitches))}",
            )
        )
    team_matches = max_matches_per_team(fmt)
    team_capacity = len(policy.days) * policy.max_matches_per_team_per_day
    if team_matches > team_capacity:
        issues.append(
            Issue(
                "schedule_team_days_insufficient",
                "schedule.max_matches_per_team_per_day",
                f"a team can play up to {team_matches} matches, but {len(policy.days)} day(s) "
                f"x {policy.max_matches_per_team_per_day} per day allow only {team_capacity}",
            )
        )
    if policy.group_stage_ends_by_day is not None and policy.group_stage_ends_by_day > len(
        policy.days
    ):
        issues.append(
            Issue(
                "schedule_days_invalid",
                "schedule.group_stage_ends_by_day",
                f"day {policy.group_stage_ends_by_day} is after the last tournament day",
            )
        )

    issues += _fixed_slot_issues(policy, fmt)
    return issues


def _calendar_issues(policy: SchedulePolicy) -> list[Issue]:
    issues: list[Issue] = []
    dates = [day.date for day in policy.days]
    if dates != sorted(set(dates)):
        issues.append(
            Issue(
                "schedule_days_invalid",
                "schedule.days",
                "tournament days must be different dates, in order",
            )
        )
    for index, day in enumerate(policy.days):
        start, end = minute_of_day(day.start), minute_of_day(day.end)
        if end <= start:
            issues.append(
                Issue(
                    "schedule_window_invalid",
                    f"schedule.days[{index}]",
                    f"the day must end after it starts ({day.start:%H:%M}-{day.end:%H:%M})",
                )
            )
            continue
        for block_index, (block_start, block_end) in enumerate(day.blocked):
            b_start, b_end = minute_of_day(block_start), minute_of_day(block_end)
            if not start <= b_start < b_end <= end:
                issues.append(
                    Issue(
                        "schedule_window_invalid",
                        f"schedule.days[{index}].blocked[{block_index}]",
                        f"the break {block_start:%H:%M}-{block_end:%H:%M} must lie inside "
                        f"the day ({day.start:%H:%M}-{day.end:%H:%M})",
                    )
                )
    return issues


def _fixed_slot_issues(policy: SchedulePolicy, fmt: FormatSpec) -> list[Issue]:
    issues: list[Issue] = []
    codes = set(all_match_codes(fmt))
    days = {day.date: day for day in policy.days}
    for index, slot in enumerate(policy.fixed_slots):
        path = f"schedule.fixed_slots[{index}]"
        day = days.get(slot.date)
        problem = None
        if slot.match_code not in codes:
            problem = f"there is no match '{slot.match_code}' in this format"
        elif day is None:
            problem = f"{slot.date.isoformat()} is not a tournament day"
        elif slot.pitch is not None and slot.pitch not in policy.pitches:
            problem = f"pitch '{slot.pitch}' is not one of the tournament's pitches"
        else:
            start = minute_of_day(slot.start)
            fits = any(
                seg_start <= start and start + policy.match_minutes <= seg_end
                for seg_start, seg_end in free_segments(day)
            )
            if not fits:
                problem = f"{slot.start:%H:%M} is outside the playing time that day"
        if problem:
            issues.append(Issue("fixed_slot_invalid", path, problem))
    return issues
