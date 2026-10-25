"""Formats that fit: the `format_auto` entry of the policy catalogue (docs/04-engine.md).

For any number of teams, lists group-then-knockout formats (plus a league or a pure
knockout where they suit), keeps only those the schedule engine can fit into the days and
pitches, and ranks them by what community tournaments and international practice favour:
groups of four, qualifying by place rather than across groups, equal groups, at least three
matches per team and a knockout to finish; then more knockout places, a third-place match
where there are semi-finals, and fewer matches.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from engine.bracket import build_bracket
from engine.rules.format import (
    FormatChoice,
    first_round_for,
    groups_then_knockout,
    knockout_only,
    league,
    max_matches_per_team,
    total_match_count,
)
from engine.rules.schedule_policy import SchedulePolicy, total_slots
from engine.schedule import ScheduleInfeasible, build_schedule

MIN_GROUP_SIZE = 3
MAX_GROUP_SIZE = 6
MAX_LEAGUE_SIZE = 8
_SEED = b"format-auto"
_ROUND_NAMES = {
    "round_of_16": "round of 16",
    "quarter_final": "quarter-finals",
    "semi_final": "semi-finals",
    "final": "final",
}
_PLACES = {  # singular, plural
    2: ("runner-up", "runners-up"),
    3: ("third-placed team", "third-placed teams"),
    4: ("fourth-placed team", "fourth-placed teams"),
}


@dataclass(frozen=True)
class FormatCandidate:
    choice: FormatChoice
    summary: str  # "4 groups of 4 · top 2 → quarter-finals · third-place match · 32 matches"
    matches: int
    min_matches_per_team: int
    max_matches_per_team: int
    qualifiers: int  # teams reaching the knockout; 0 without one


def _sizes(team_count: int, group_count: int) -> list[int]:
    base, extra = divmod(team_count, group_count)
    return [base + 1] * extra + [base] * (group_count - extra)


def _structures(team_count: int) -> Iterator[FormatChoice]:
    """Every sensible format for the team count, with a third-place match where possible."""
    for group_count in range(1, team_count // MIN_GROUP_SIZE + 1):
        sizes = _sizes(team_count, group_count)
        if min(sizes) < MIN_GROUP_SIZE or max(sizes) > MAX_GROUP_SIZE:
            continue
        for per_group in (1, 2, 4) if group_count == 1 else (1, 2):
            for best_of_rest in range(group_count if group_count > 1 else 1):
                qualifiers = group_count * per_group + best_of_rest
                if per_group >= min(sizes) or qualifiers >= team_count:
                    continue
                round_ = first_round_for(qualifiers)
                if round_ is None:
                    continue
                try:
                    yield groups_then_knockout(
                        sizes,
                        per_group=per_group,
                        best_of_rest=best_of_rest,
                        third_place_match=qualifiers >= 4,
                    )
                except ValueError:
                    continue
    if team_count <= MAX_LEAGUE_SIZE:
        yield league(team_count)
    if first_round_for(team_count) is not None:
        yield knockout_only(team_count, third_place_match=team_count >= 4)


def _without_third_place(choice: FormatChoice) -> FormatChoice | None:
    knockout = choice.format.knockout
    if knockout is None or not knockout.third_place_match:
        return None
    fmt = choice.format.model_copy(
        update={"knockout": knockout.model_copy(update={"third_place_match": False})}
    )
    return FormatChoice(fmt, choice.advancement)


def _min_matches(choice: FormatChoice) -> int:
    fmt = choice.format
    if fmt.group_sizes:
        return (min(fmt.group_sizes) - 1) * fmt.group_rounds
    return 1


def _qualifiers(choice: FormatChoice) -> int:
    fmt, advancement = choice.format, choice.advancement
    if fmt.knockout is None:
        return 0
    if not fmt.group_sizes:
        return fmt.team_count
    return fmt.group_count * advancement.per_group + advancement.best_of_rest


def _summary(choice: FormatChoice) -> str:
    fmt, advancement = choice.format, choice.advancement
    knockout = fmt.knockout
    parts: list[str] = []
    if knockout is None:
        parts.append(f"league of {fmt.team_count} · everyone plays everyone once")
    elif not fmt.group_sizes:
        parts.append(f"knockout of {fmt.team_count}")
    else:
        sizes = fmt.group_sizes
        if len(set(sizes)) == 1:
            plural = "s" if len(sizes) > 1 else ""
            parts.append(f"{len(sizes)} group{plural} of {sizes[0]}")
        else:
            parts.append(f"{len(sizes)} groups ({', '.join(map(str, sizes))})")
        top = "group winners" if advancement.per_group == 1 else f"top {advancement.per_group}"
        if advancement.best_of_rest:
            one, many = _PLACES.get(advancement.per_group + 1, ("next-placed team", "teams"))
            count = advancement.best_of_rest
            top += f" + the best {one}" if count == 1 else f" + {count} best {many}"
        parts.append(f"{top} → {_ROUND_NAMES[knockout.rounds[0]]}")
    if knockout is not None and knockout.third_place_match:
        parts.append("third-place match")
    parts.append(f"{total_match_count(fmt)} matches")
    return " · ".join(parts)


def _candidate(choice: FormatChoice) -> FormatCandidate:
    return FormatCandidate(
        choice=choice,
        summary=_summary(choice),
        matches=total_match_count(choice.format),
        min_matches_per_team=_min_matches(choice),
        max_matches_per_team=max_matches_per_team(choice.format),
        qualifiers=_qualifiers(choice),
    )


def _rank(candidate: FormatCandidate) -> tuple[int, int, int, int]:
    fmt, advancement = candidate.choice.format, candidate.choice.advancement
    sizes = fmt.group_sizes or [fmt.team_count]
    penalty = max(abs(size - 4) for size in sizes) if fmt.group_sizes else 0
    penalty += 1 if advancement.best_of_rest else 0
    penalty += 1 if len(set(sizes)) > 1 else 0
    penalty += max(0, 3 - candidate.min_matches_per_team)
    penalty += 1 if fmt.knockout is None else 0
    third_place = fmt.knockout is not None and fmt.knockout.third_place_match
    return (penalty, -candidate.qualifiers, -int(third_place), candidate.matches)


def _could_fit(choice: FormatChoice, policy: SchedulePolicy) -> bool:
    """Cheap necessary conditions, checked before running the scheduler."""
    fmt = choice.format
    last_round = max((size // 2 for size in fmt.group_sizes), default=0)
    return (
        total_match_count(fmt) <= total_slots(policy)
        and max_matches_per_team(fmt) <= len(policy.days) * policy.max_matches_per_team_per_day
        and (not policy.simultaneous_last_group_round or last_round <= len(policy.pitches))
    )


def _fits(choice: FormatChoice, policy: SchedulePolicy) -> bool:
    if not _could_fit(choice, policy):
        return False
    fmt = choice.format
    groups: list[list[str]] = []
    for index, size in enumerate(fmt.group_sizes):
        groups.append([f"team-{index}-{i}" for i in range(size)])
    bracket = build_bracket(fmt, choice.advancement) if fmt.knockout is not None else None
    try:
        build_schedule(groups, bracket, policy, seed=_SEED, group_rounds=fmt.group_rounds)
    except ScheduleInfeasible:
        return False
    return True


def format_auto(
    team_count: int, policy: SchedulePolicy, *, limit: int = 5
) -> list[FormatCandidate]:
    """Ranked formats for `team_count` teams that fit the policy's days and pitches.

    Empty when nothing fits; `engine.schedule.suggest_relaxations` then says what to change.
    """
    candidates = sorted((_candidate(c) for c in _structures(team_count)), key=_rank)
    fitting: list[FormatCandidate] = []
    for candidate in candidates:
        if len(fitting) >= limit:
            break
        choice = candidate.choice
        if not _fits(choice, policy):
            fallback = _without_third_place(choice)
            if fallback is None or not _fits(fallback, policy):
                continue
            choice = fallback
        found = _candidate(choice)
        if all(found.summary != other.summary for other in fitting):
            fitting.append(found)
    return fitting
