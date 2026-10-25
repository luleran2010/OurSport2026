"""Match schedules: when and on which pitch every match is played (docs/04-engine.md).

Building (`build_schedule`):
- group matches follow Berger round-robin tables; a group's last round kicks off together
  when `simultaneous_last_group_round` is set;
- slots come from days x free segments (window minus breaks) x pitches; every time is
  computed from the day's own UTC offset;
- the knockout is placed first, as late as possible (the final on the main pitch in the
  last slot, after the third-place match), then the group rounds as early as possible,
  spread over the days before it. If that fails, simpler strategies are tried. The seed only
  decides which group goes first in each round, so the plan is reproducible;
- finally, matches that kick off together swap pitches so every team gets its turn on the
  main pitch (usually the filmed one).

Knockout participants are unknown while scheduling, so a knockout match counts for every
team that could reach it (`teams`). Matches of the same knockout round never clash (a team
plays only one of them); the third-place match and the final count as one round.

`schedule_violations` checks a plan independently of how it was built, `reschedule` moves
the fewest unstarted matches after a change on match day, and `suggest_relaxations` lists
what would make an infeasible schedule fit.
"""

import datetime as dt
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import Literal

from engine.bracket import Bracket, BracketRound
from engine.rng import DeterministicRng
from engine.rules.format import THIRD_PLACE_CODE, group_letter
from engine.rules.schedule_policy import (
    DayWindow,
    SchedulePolicy,
    free_segments,
    minute_of_day,
    slots_in_segment,
    total_slots,
)

SCHEDULE_ALGORITHM = "schedule-1"

type MatchStage = Literal["group"] | BracketRound
type Strategy = Literal["knockout_last_spread", "knockout_last", "in_order", "reschedule"]

STRATEGIES: tuple[Strategy, ...] = ("knockout_last_spread", "knockout_last", "in_order")

_EPOCH = dt.date(1970, 1, 1)
_FOREVER = 1 << 40
_FINAL = "F"
_STAGE_WEIGHT: Mapping[str, int] = {
    "round_of_16": 1,
    "quarter_final": 2,
    "semi_final": 3,
    "third_place": 4,
    "final": 5,
}
_EARLIEST_START = 6 * 60
_LATEST_END = 23 * 60 + 30


# --- results ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledMatch:
    code: str  # "A1", "QF1", "F"
    stage: MatchStage
    group: str | None  # "A" for group matches
    round: int | None  # group round, 1-based
    home: str | None  # team id; None while a knockout slot is still a placeholder
    away: str | None
    home_source: str | None  # knockout placeholder ("group:A:1"); None for group matches
    away_source: str | None
    teams: tuple[str, ...]  # every team that could play in it
    depends_on: tuple[str, ...]  # must be finished, plus rest, before this match starts
    follows: tuple[str, ...]  # must be finished before it starts (the final follows 3P)
    together: str | None  # matches sharing this key kick off together (a last group round)
    day: int  # 1-based tournament day
    pitch: str
    start: int  # minutes since the Unix epoch, UTC
    end: int
    local_date: dt.date
    local_time: dt.time

    @property
    def starts_at(self) -> str:
        return _iso(self.start)

    @property
    def ends_at(self) -> str:
        return _iso(self.end)

    @property
    def level(self) -> str:
        """Matches on the same knockout level never share a team."""
        return _level(self.code, self.stage)


@dataclass(frozen=True)
class ScheduleQuality:
    hard_violations: int
    min_rest_minutes: int | None  # shortest break any team gets between two matches
    max_idle_minutes: int | None  # longest wait any team has between matches on one day
    main_pitch_spread: int  # most minus fewest group matches a team plays on the main pitch
    group_stage_last_day: int | None
    final_in_best_slot: bool | None  # main pitch, last slot of the last day


@dataclass(frozen=True)
class SchedulePlan:
    matches: tuple[ScheduledMatch, ...]  # by start time, then pitch order
    walkovers: tuple[str, ...]  # codes no longer played (a team withdrew)
    quality: ScheduleQuality
    seed: bytes
    strategy: Strategy
    moved: tuple[str, ...] = ()  # codes a reschedule moved
    algorithm: str = SCHEDULE_ALGORITHM


@dataclass(frozen=True)
class ScheduleViolation:
    kind: str  # "pitch_double_booked", "team_rest", "too_many_matches_in_a_day", …
    matches: tuple[str, ...]
    message: str


class ScheduleInfeasible(Exception):
    def __init__(
        self,
        message: str,
        *,
        unplaced: Sequence[str] = (),
        matches: int = 0,
        slots: int = 0,
        violations: Sequence[ScheduleViolation] = (),
    ) -> None:
        super().__init__(message)
        self.unplaced = tuple(unplaced)
        self.matches = matches
        self.slots = slots
        self.violations = tuple(violations)


# --- match-day changes -----------------------------------------------------------------------


@dataclass(frozen=True)
class PitchDelay:
    """The pitch is running late: its current match ends `minutes` later than planned."""

    pitch: str
    minutes: int


@dataclass(frozen=True)
class PitchClosed:
    pitch: str
    until: str | None = None  # ISO 8601 UTC; None: for the rest of the tournament


@dataclass(frozen=True)
class TeamWithdrawn:
    team: str  # its unplayed group matches become walkovers


@dataclass(frozen=True)
class MatchPostponed:
    code: str
    not_before: str | None = None  # ISO 8601 UTC; None: any later slot


type ScheduleChange = PitchDelay | PitchClosed | TeamWithdrawn | MatchPostponed


@dataclass(frozen=True)
class Relaxation:
    kind: str  # "add_pitch", "shorter_matches", "longer_days", "more_matches_per_day", …
    summary: str  # plain language, for the organiser's question
    policy: SchedulePolicy  # the relaxed policy
    slots: int  # match slots it gives
    feasible: bool


# --- time ------------------------------------------------------------------------------------


def _utc_minute(date: dt.date, local_minute: int, offset: int) -> int:
    return (date - _EPOCH).days * 1440 + local_minute - offset


def _iso(minute: int) -> str:
    moment = dt.datetime(1970, 1, 1) + dt.timedelta(minutes=minute)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> int:
    """Minutes since the epoch, rounded up: a match starting before this has started."""
    moment = dt.datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.UTC).replace(tzinfo=None)
    return math.ceil((moment - dt.datetime(1970, 1, 1)).total_seconds() / 60)


def _local(day: DayWindow, start: int) -> tuple[dt.date, dt.time]:
    minute = start + day.utc_offset_minutes - (day.date - _EPOCH).days * 1440
    return day.date, dt.time(minute // 60, minute % 60)


@dataclass(frozen=True)
class _Time:
    start: int  # UTC minute
    day: int  # 0-based day index


def _grid(policy: SchedulePolicy) -> list[_Time]:
    """Every start time a match may use, in order; the same on every pitch."""
    times: list[_Time] = []
    step = policy.match_minutes + policy.break_minutes
    for index, day in enumerate(policy.days):
        for seg_start, seg_end in free_segments(day):
            count = slots_in_segment(
                seg_end - seg_start, policy.match_minutes, policy.break_minutes
            )
            times.extend(
                _Time(_utc_minute(day.date, seg_start + k * step, day.utc_offset_minutes), index)
                for k in range(count)
            )
    return sorted(times, key=lambda t: t.start)


# --- matches to schedule ---------------------------------------------------------------------


def berger_rounds(teams: Sequence[str]) -> list[list[tuple[str, str]]]:
    """Round-robin rounds by the circle method, home and away alternating (Berger tables).

    With an odd number of teams one team rests each round. In a group of four the first two
    teams meet in the last round, as at World Cups.
    """
    slots: list[str | None] = list(teams)
    if len(slots) % 2:
        slots.append(None)  # a bye
    size = len(slots)
    rounds: list[list[tuple[str, str]]] = []
    for r in range(size - 1):
        pairs: list[tuple[str, str]] = []
        for i in range(size // 2):
            home, away = slots[i], slots[size - 1 - i]
            if (i == 0 and r % 2 == 1) or (i > 0 and i % 2 == 1):
                home, away = away, home
            if home is not None and away is not None:
                pairs.append((home, away))
        rounds.append(pairs)
        slots = [slots[0], slots[-1], *slots[1:-1]]
    return rounds


def _level(code: str, stage: str) -> str:
    if stage == "group":
        return f"group:{code}"
    return "final" if stage == "third_place" else stage


@dataclass(frozen=True)
class _Spec:
    code: str
    stage: MatchStage
    group: str | None
    round: int | None
    home: str | None
    away: str | None
    home_source: str | None
    away_source: str | None
    teams: frozenset[str]
    depends_on: tuple[str, ...]
    follows: tuple[str, ...]
    together: str | None

    @property
    def level(self) -> str:
        return _level(self.code, self.stage)


type _Rounds = list[list[list[str]]]  # match codes per group, per round


def _group_specs(
    groups: Sequence[Sequence[str]], group_rounds: int, together: bool
) -> tuple[list[_Spec], _Rounds]:
    specs: list[_Spec] = []
    by_round: _Rounds = []
    for index, teams in enumerate(groups):
        letter = group_letter(index)
        legs = berger_rounds(teams)
        rounds = legs + [[(a, h) for h, a in leg] for leg in legs] if group_rounds == 2 else legs
        codes_per_round: list[list[str]] = []
        number = 0
        for r, pairs in enumerate(rounds, start=1):
            key = f"last:{letter}" if together and r == len(rounds) and len(pairs) > 1 else None
            codes: list[str] = []
            for home, away in pairs:
                number += 1
                code = f"{letter}{number}"
                specs.append(
                    _Spec(
                        code=code,
                        stage="group",
                        group=letter,
                        round=r,
                        home=home,
                        away=away,
                        home_source=None,
                        away_source=None,
                        teams=frozenset({home, away}),
                        depends_on=(),
                        follows=(),
                        together=key,
                    )
                )
                codes.append(code)
            codes_per_round.append(codes)
        by_round.append(codes_per_round)
    return specs, by_round


def _knockout_specs(
    groups: Sequence[Sequence[str]], by_round: _Rounds, bracket: Bracket
) -> list[_Spec]:
    group_teams = {group_letter(i): frozenset(teams) for i, teams in enumerate(groups)}
    group_codes = {
        group_letter(i): tuple(code for codes in rounds for code in codes)
        for i, rounds in enumerate(by_round)
    }
    every_team = frozenset(team for teams in groups for team in teams)
    every_group_match = tuple(code for codes in group_codes.values() for code in codes)
    specs: dict[str, _Spec] = {}

    def resolve(source: str) -> tuple[frozenset[str], tuple[str, ...]]:
        kind, _, rest = source.partition(":")
        if kind == "group":
            letter = rest.partition(":")[0]
            if letter not in group_teams:
                raise ValueError(f"placeholder '{source}' names a group that does not exist")
            return group_teams[letter], group_codes[letter]
        if kind == "best_rest":
            return every_team, every_group_match
        if kind in ("winner", "loser"):
            return specs[rest].teams, (rest,)
        return frozenset({source}), ()  # seed:k — a team known only once the draw is made

    codes = {match.code for match in bracket.matches}
    for match in bracket.matches:
        home_teams, home_after = resolve(match.home_source)
        away_teams, away_after = resolve(match.away_source)
        follows = (THIRD_PLACE_CODE,) if match.code == _FINAL and THIRD_PLACE_CODE in codes else ()
        specs[match.code] = _Spec(
            code=match.code,
            stage=match.round,
            group=None,
            round=None,
            home=None,
            away=None,
            home_source=match.home_source,
            away_source=match.away_source,
            teams=home_teams | away_teams,
            depends_on=tuple(sorted(set(home_after) | set(away_after))),
            follows=follows,
            together=None,
        )
    return list(specs.values())


def _spec_of(match: ScheduledMatch) -> _Spec:
    return _Spec(
        code=match.code,
        stage=match.stage,
        group=match.group,
        round=match.round,
        home=match.home,
        away=match.away,
        home_source=match.home_source,
        away_source=match.away_source,
        teams=frozenset(match.teams),
        depends_on=match.depends_on,
        follows=match.follows,
        together=match.together,
    )


# --- placing ---------------------------------------------------------------------------------


@dataclass
class _Placed:
    start: int
    end: int
    pitch: str
    day: int  # 0-based


class _Planner:
    """Places matches one by one, checking every hard constraint against those placed."""

    def __init__(
        self,
        specs: Mapping[str, _Spec],
        policy: SchedulePolicy,
        blocked: Mapping[str, Sequence[tuple[int, int]]] | None = None,
    ) -> None:
        self.specs = specs
        self.policy = policy
        self.length = policy.match_minutes
        self.blocked = blocked or {}
        self.successors: dict[str, list[str]] = defaultdict(list)
        self.followers: dict[str, list[str]] = defaultdict(list)
        for spec in specs.values():
            for code in spec.depends_on:
                self.successors[code].append(spec.code)
            for code in spec.follows:
                self.followers[code].append(spec.code)
        self.placed: dict[str, _Placed] = {}
        self._by_team: dict[str, set[str]] = defaultdict(set)
        self._by_pitch: dict[str, set[str]] = defaultdict(set)

    def fits(self, code: str, start: int, pitch: str, day: int) -> bool:
        spec, policy = self.specs[code], self.policy
        end = start + self.length
        gap, rest = policy.break_minutes, policy.min_rest_minutes
        if any(start < until and since < end for since, until in self.blocked.get(pitch, ())):
            return False
        for other in self._by_pitch[pitch]:
            placed = self.placed[other]
            if start < placed.end + gap and placed.start < end + gap:
                return False
        if not self._ordered(code, start, end, rest):
            return False
        knockout = spec.stage != "group"
        for team in spec.teams:
            levels = {spec.level}
            for other in self._by_team[team]:
                placed, other_spec = self.placed[other], self.specs[other]
                if placed.day == day:
                    levels.add(other_spec.level)
                if knockout and other_spec.level == spec.level:
                    continue  # the same knockout round: a team plays only one of them
                if start < placed.end + rest and placed.start < end + rest:
                    return False
            if len(levels) > policy.max_matches_per_team_per_day:
                return False
        return True

    def _ordered(self, code: str, start: int, end: int, rest: int) -> bool:
        spec = self.specs[code]
        checks = (
            [(self.placed.get(c), True, rest) for c in spec.depends_on]
            + [(self.placed.get(c), False, rest) for c in self.successors[code]]
            + [(self.placed.get(c), True, 0) for c in spec.follows]
            + [(self.placed.get(c), False, 0) for c in self.followers[code]]
        )
        for placed, before, wait in checks:
            if placed is None:
                continue
            if before and start < placed.end + wait:
                return False
            if not before and placed.start < end + wait:
                return False
        return True

    def place(self, code: str, start: int, pitch: str, day: int, end: int | None = None) -> None:
        self.placed[code] = _Placed(start, start + self.length if end is None else end, pitch, day)
        for team in self.specs[code].teams:
            self._by_team[team].add(code)
        self._by_pitch[pitch].add(code)

    def remove(self, code: str) -> None:
        placed = self.placed.pop(code)
        for team in self.specs[code].teams:
            self._by_team[team].discard(code)
        self._by_pitch[placed.pitch].discard(code)

    def place_unit(
        self,
        codes: Sequence[str],
        times: Iterable[_Time],
        prefer: Mapping[str, str] | None = None,
    ) -> bool:
        """Place matches that kick off together at the first time in `times` that fits."""
        todo = [code for code in codes if code not in self.placed]
        if not todo:
            return True
        anchored = [self.placed[code] for code in codes if code in self.placed]
        if anchored:  # part of the unit is fixed: the rest joins it
            times = [_Time(anchored[0].start, anchored[0].day)]
        pitches = self.policy.pitches
        for time in times:
            chosen: list[str] = []
            for code in todo:
                order = pitches
                if prefer and code in prefer:
                    order = [prefer[code], *(p for p in pitches if p != prefer[code])]
                pitch = next((p for p in order if self.fits(code, time.start, p, time.day)), None)
                if pitch is None:
                    break
                self.place(code, time.start, pitch, time.day)
                chosen.append(code)
            if len(chosen) == len(todo):
                return True
            for code in chosen:
                self.remove(code)
        return False


def _units(codes: Sequence[str], specs: Mapping[str, _Spec]) -> list[list[str]]:
    """Matches grouped into units that kick off together, in order of first appearance."""
    units: list[list[str]] = []
    keyed: dict[str, list[str]] = {}
    for code in codes:
        key = specs[code].together
        if key is None:
            units.append([code])
        elif key in keyed:
            keyed[key].append(code)
        else:
            keyed[key] = [code]
            units.append(keyed[key])
    return units


def _group_levels(by_round: _Rounds, order: Sequence[int]) -> list[list[str]]:
    """Group match codes per round across groups; the group that starts rotates each round."""
    levels: list[list[str]] = []
    for level in range(max((len(rounds) for rounds in by_round), default=0)):
        shift = level % len(order)
        rotated = [*order[shift:], *order[:shift]]
        levels.append(
            [code for g in rotated if level < len(by_round[g]) for code in by_round[g][level]]
        )
    return levels


def _place_fixed(planner: _Planner, policy: SchedulePolicy) -> tuple[list[str], set[str]]:
    """Place the organiser's fixed slots; returns those that could not be placed and the
    codes whose pitch is fixed too."""
    days = {day.date: (index, day) for index, day in enumerate(policy.days)}
    unplaced: list[str] = []
    pinned_pitch: set[str] = set()
    for slot in policy.fixed_slots:
        code = slot.match_code
        if code not in planner.specs or slot.date not in days:
            unplaced.append(code)
            continue
        index, day = days[slot.date]
        start = _utc_minute(slot.date, minute_of_day(slot.start), day.utc_offset_minutes)
        pitches = [slot.pitch] if slot.pitch else policy.pitches
        pitch = next((p for p in pitches if planner.fits(code, start, p, index)), None)
        if pitch is None:
            unplaced.append(code)
            continue
        planner.place(code, start, pitch, index)
        if slot.pitch:
            pinned_pitch.add(code)
    return unplaced, pinned_pitch


def _releases(
    planner: _Planner, levels: int, grid: Sequence[_Time], policy: SchedulePolicy
) -> list[int]:
    """Earliest start of each group round, spreading the rounds over the group-stage days."""
    first_start: dict[int, int] = {}
    for time in grid:
        first_start.setdefault(time.day, time.start)
    knockout_days = [
        placed.day
        for code, placed in planner.placed.items()
        if planner.specs[code].stage != "group"
    ]
    days = sorted(first_start)
    if knockout_days:
        days = [d for d in days if d < min(knockout_days)] or [min(knockout_days)]
    if policy.group_stage_ends_by_day is not None:
        days = [d for d in days if d < policy.group_stage_ends_by_day] or days[:1]
    days = [d for d in days if d in first_start]
    if not days:
        return [grid[0].start if grid else 0] * levels
    return [first_start[days[level * len(days) // levels]] for level in range(levels)]


def _attempt(
    strategy: Strategy,
    specs: Mapping[str, _Spec],
    levels: Sequence[Sequence[str]],
    knockout: Sequence[str],
    grid: Sequence[_Time],
    policy: SchedulePolicy,
) -> tuple[_Planner, list[str], set[str]]:
    planner = _Planner(specs, policy)
    unplaced, pinned_pitch = _place_fixed(planner, policy)

    def place(units: Iterable[list[str]], times: Sequence[_Time]) -> None:
        for unit in units:
            if not planner.place_unit(unit, times):
                unplaced.extend(code for code in unit if code not in planner.placed)

    if strategy == "in_order":
        for level in levels:
            place(_units(level, specs), grid)
        place(([code] for code in knockout), grid)
        return planner, unplaced, pinned_pitch

    latest_first = list(reversed(grid))
    place(([code] for code in reversed(knockout)), latest_first)
    if strategy == "knockout_last_spread" and levels:
        releases = _releases(planner, len(levels), grid, policy)
    else:
        releases = [grid[0].start if grid else 0] * len(levels)
    for level, release in zip(levels, releases, strict=True):
        place(_units(level, specs), [t for t in grid if t.start >= release])
    return planner, unplaced, pinned_pitch


def _balance_pitches(planner: _Planner, policy: SchedulePolicy, locked: set[str]) -> None:
    """Among matches kicking off together, give the main pitch to the knockout match of the
    latest round, else to the teams that have played on it least."""
    main = policy.pitches[0]
    rank = {pitch: index for index, pitch in enumerate(policy.pitches)}
    on_main: Counter[str] = Counter()
    together: dict[tuple[int, int], list[str]] = defaultdict(list)
    for code, placed in planner.placed.items():
        together[(placed.start, placed.end)].append(code)

    for key in sorted(together):
        codes = sorted(together[key])
        free = [code for code in codes if code not in locked]
        pitches = sorted((planner.placed[code].pitch for code in free), key=rank.__getitem__)

        def priority(code: str) -> tuple[int, int, int, str]:
            spec = planner.specs[code]
            if spec.stage != "group":
                return (0, -_STAGE_WEIGHT[spec.stage], 0, code)
            counts = [on_main[team] for team in spec.teams]
            return (1, max(counts), sum(counts), code)

        for code, pitch in zip(sorted(free, key=priority), pitches, strict=True):
            planner.placed[code].pitch = pitch
        for code in codes:
            spec = planner.specs[code]
            if spec.stage == "group" and planner.placed[code].pitch == main:
                on_main.update(spec.teams)


def _scheduled(spec: _Spec, placed: _Placed, policy: SchedulePolicy) -> ScheduledMatch:
    local_date, local_time = _local(policy.days[placed.day], placed.start)
    return ScheduledMatch(
        code=spec.code,
        stage=spec.stage,
        group=spec.group,
        round=spec.round,
        home=spec.home,
        away=spec.away,
        home_source=spec.home_source,
        away_source=spec.away_source,
        teams=tuple(sorted(spec.teams)),
        depends_on=spec.depends_on,
        follows=spec.follows,
        together=spec.together,
        day=placed.day + 1,
        pitch=placed.pitch,
        start=placed.start,
        end=placed.end,
        local_date=local_date,
        local_time=local_time,
    )


def _plan(
    planner: _Planner,
    policy: SchedulePolicy,
    *,
    seed: bytes,
    strategy: Strategy,
    walkovers: Sequence[str] = (),
    moved: Sequence[str] = (),
    check_fixed: bool = True,
) -> tuple[SchedulePlan, list[ScheduleViolation]]:
    rank = {pitch: index for index, pitch in enumerate(policy.pitches)}
    matches = tuple(
        sorted(
            (
                _scheduled(planner.specs[code], placed, policy)
                for code, placed in planner.placed.items()
            ),
            key=lambda m: (m.start, rank.get(m.pitch, len(rank)), m.code),
        )
    )
    violations = _violations(matches, policy, check_fixed=check_fixed)
    plan = SchedulePlan(
        matches=matches,
        walkovers=tuple(walkovers),
        quality=_quality(matches, policy, len(violations)),
        seed=seed,
        strategy=strategy,
        moved=tuple(moved),
    )
    return plan, violations


def build_schedule(
    groups: Sequence[Sequence[str]],
    bracket: Bracket | None,
    policy: SchedulePolicy,
    *,
    seed: bytes,
    group_rounds: Literal[1, 2] = 1,
) -> SchedulePlan:
    """Every match of the tournament on a pitch and a time, or `ScheduleInfeasible`.

    `groups` are team ids per group in draw order (A, B, …); `bracket` is None without a
    knockout. Knockout-only formats pass no groups.
    """
    group_list, by_round = _group_specs(groups, group_rounds, policy.simultaneous_last_group_round)
    knockout = _knockout_specs(groups, by_round, bracket) if bracket is not None else []
    specs = {spec.code: spec for spec in [*group_list, *knockout]}
    grid = _grid(policy)
    order = DeterministicRng(seed).shuffled(range(len(groups)))
    levels = _group_levels(by_round, order)
    knockout_codes = [spec.code for spec in knockout]

    best: tuple[_Planner, list[str]] | None = None
    for strategy in STRATEGIES:
        planner, unplaced, pinned_pitch = _attempt(
            strategy, specs, levels, knockout_codes, grid, policy
        )
        if not unplaced:
            break
        if best is None or len(unplaced) < len(best[1]):
            best = (planner, unplaced)
    else:
        assert best is not None
        missing = best[1]
        raise ScheduleInfeasible(
            f"{len(missing)} of {len(specs)} matches do not fit "
            f"({', '.join(missing[:5])}{', …' if len(missing) > 5 else ''}); "
            f"the days and pitches give {total_slots(policy)} slots",
            unplaced=missing,
            matches=len(specs),
            slots=total_slots(policy),
        )

    locked = set(pinned_pitch)
    if policy.final_on_main_pitch_last_slot and _FINAL in planner.placed:
        locked.add(_FINAL)
    _balance_pitches(planner, policy, locked)
    plan, violations = _plan(planner, policy, seed=seed, strategy=strategy)
    if violations:  # only the organiser's fixed slots can cause this
        raise ScheduleInfeasible(
            "; ".join(v.message for v in violations[:3]),
            matches=len(specs),
            slots=total_slots(policy),
            violations=violations,
        )
    return plan


# --- checking --------------------------------------------------------------------------------


def schedule_violations(
    plan: SchedulePlan, policy: SchedulePolicy, *, check_fixed: bool = True
) -> list[ScheduleViolation]:
    """Every hard constraint the plan breaks, checked from the plan alone.

    `check_fixed=False` after a reschedule, which may have to move a fixed match.
    """
    return _violations(plan.matches, policy, check_fixed=check_fixed)


def _violations(
    matches: Sequence[ScheduledMatch], policy: SchedulePolicy, *, check_fixed: bool
) -> list[ScheduleViolation]:
    found: list[ScheduleViolation] = []

    def add(kind: str, codes: Iterable[str], message: str) -> None:
        found.append(ScheduleViolation(kind, tuple(codes), message))

    found += _where_and_when(matches, policy)
    rest, gap = policy.min_rest_minutes, policy.break_minutes
    by_pitch: dict[str, list[ScheduledMatch]] = defaultdict(list)
    by_team: dict[str, list[ScheduledMatch]] = defaultdict(list)
    for match in matches:
        by_pitch[match.pitch].append(match)
        for team in match.teams:
            by_team[team].append(match)

    for pitch, on_pitch in sorted(by_pitch.items()):
        for a, b in combinations(on_pitch, 2):
            if a.start < b.end + gap and b.start < a.end + gap:
                add("pitch_double_booked", (a.code, b.code), f"{a.code} and {b.code} share {pitch}")

    seen: set[tuple[str, str]] = set()
    for team, played in sorted(by_team.items()):
        ordered = sorted(played, key=lambda m: (m.start, m.code))
        for a, b in combinations(ordered, 2):
            same_round = a.stage != "group" and b.stage != "group" and a.level == b.level
            if same_round or (a.code, b.code) in seen or b.start >= a.end + rest:
                continue
            seen.add((a.code, b.code))
            kind = "team_clash" if b.start < a.end else "team_rest"
            add(
                kind, (a.code, b.code), f"{team} has under {rest} min between {a.code} and {b.code}"
            )
        levels: dict[int, set[str]] = defaultdict(set)
        for match in played:
            levels[match.day].add(match.level)
        for day, on_day in sorted(levels.items()):
            if len(on_day) > policy.max_matches_per_team_per_day:
                add(
                    "too_many_matches_in_a_day",
                    sorted(m.code for m in played if m.day == day),
                    f"{team} could play {len(on_day)} matches on day {day}",
                )

    by_code = {match.code: match for match in matches}
    for match in matches:
        needs = [(c, rest) for c in match.depends_on] + [(c, 0) for c in match.follows]
        for code, wait in needs:
            before = by_code.get(code)
            if before is not None and match.start < before.end + wait:
                add("dependency_order", (code, match.code), f"{match.code} starts before {code}")

    starts: dict[str, set[int]] = defaultdict(set)
    for match in matches:
        if match.together is not None:
            starts[match.together].add(match.start)
    for key, times in sorted(starts.items()):
        if len(times) > 1:
            codes = sorted(m.code for m in matches if m.together == key)
            add("last_round_not_together", codes, f"{', '.join(codes)} must kick off together")

    if check_fixed:
        for slot in policy.fixed_slots:
            fixed = by_code.get(slot.match_code)
            if fixed is not None and (
                (fixed.local_date, fixed.local_time) != (slot.date, slot.start)
                or (slot.pitch is not None and fixed.pitch != slot.pitch)
            ):
                add("fixed_slot_moved", (fixed.code,), f"{fixed.code} is not in its fixed slot")
    return found


def _where_and_when(
    matches: Sequence[ScheduledMatch], policy: SchedulePolicy
) -> list[ScheduleViolation]:
    found: list[ScheduleViolation] = []
    pitches = set(policy.pitches)
    for match in matches:
        codes = (match.code,)
        if match.pitch not in pitches:
            found.append(ScheduleViolation("unknown_pitch", codes, f"{match.pitch} is unknown"))
        if not 1 <= match.day <= len(policy.days):
            found.append(ScheduleViolation("outside_playing_time", codes, "not a tournament day"))
            continue
        day = policy.days[match.day - 1]
        local = minute_of_day(match.local_time)
        if (
            match.local_date != day.date
            or match.start != _utc_minute(day.date, local, day.utc_offset_minutes)
            or match.end < match.start + policy.match_minutes
        ):
            found.append(ScheduleViolation("time_mismatch", codes, "local and UTC times differ"))
        if not any(
            start <= local and local + policy.match_minutes <= end
            for start, end in free_segments(day)
        ):
            found.append(
                ScheduleViolation(
                    "outside_playing_time",
                    codes,
                    f"{match.code} at {match.local_time:%H:%M} on {match.local_date} is outside "
                    "the playing time or in a break",
                )
            )
    return found


def _quality(
    matches: Sequence[ScheduledMatch], policy: SchedulePolicy, violations: int
) -> ScheduleQuality:
    played: dict[str, list[ScheduledMatch]] = defaultdict(list)
    group_matches = [m for m in matches if m.stage == "group"]
    for match in group_matches:
        for team in match.teams:
            played[team].append(match)
    rests: list[int] = []
    idles: list[int] = []
    for team_matches in played.values():
        ordered = sorted(team_matches, key=lambda m: m.start)
        for a, b in pairwise(ordered):
            rests.append(b.start - a.end)
            if a.day == b.day:
                idles.append(b.start - a.end)

    main = policy.pitches[0]
    on_main = Counter(team for m in group_matches if m.pitch == main for team in m.teams)
    counts = [on_main[team] for team in played]

    final = next((m for m in matches if m.code == _FINAL and m.stage == "final"), None)
    best_slot: bool | None = None
    if final is not None:
        last_day = [t.start for t in _grid(policy) if t.day == len(policy.days) - 1]
        best_slot = final.pitch == main and bool(last_day) and final.start == max(last_day)
    return ScheduleQuality(
        hard_violations=violations,
        min_rest_minutes=min(rests, default=None),
        max_idle_minutes=max(idles, default=None),
        main_pitch_spread=max(counts) - min(counts) if counts else 0,
        group_stage_last_day=max((m.day for m in group_matches), default=None),
        final_in_best_slot=best_slot,
    )


# --- rescheduling ----------------------------------------------------------------------------


def reschedule(
    plan: SchedulePlan,
    *,
    frozen_until: str,
    changes: Sequence[ScheduleChange],
    policy: SchedulePolicy,
) -> SchedulePlan:
    """Apply match-day changes, keeping every match that started before `frozen_until`.

    Unaffected matches stay put. Affected ones (on a closed or delayed pitch, postponed, or
    now too close to a delayed match) move to the earliest slot from their planned time,
    preferring their own pitch. If that fails, all later matches are re-placed the same way;
    as a last resort, matches on days that have not started may also move earlier that day.
    A withdrawn team's unplayed group matches become walkovers.
    """
    cutoff = _parse_utc(frozen_until)
    original = {match.code: match for match in plan.matches}
    withdrawn = {c.team for c in changes if isinstance(c, TeamWithdrawn)}
    started = [m for m in plan.matches if m.start < cutoff]
    walkovers = {
        m.code
        for m in plan.matches
        if m.start >= cutoff and m.stage == "group" and {m.home, m.away} & withdrawn
    }
    waiting = [m for m in plan.matches if m.start >= cutoff and m.code not in walkovers]

    ends = {m.code: m.end for m in started}
    blocked: dict[str, list[tuple[int, int]]] = defaultdict(list)
    not_before: dict[str, int] = {}
    for change in changes:
        match change:
            case PitchClosed(pitch, until):
                blocked[pitch].append((cutoff, _FOREVER if until is None else _parse_utc(until)))
            case PitchDelay(pitch, minutes):
                running = [m for m in started if m.pitch == pitch and m.end > cutoff]
                for m in running:
                    ends[m.code] += minutes
                if not running:
                    blocked[pitch].append((cutoff, cutoff + minutes))
            case MatchPostponed(code, later):
                if code not in original:
                    raise ValueError(f"there is no match '{code}' in this plan")
                if code in walkovers or original[code].start < cutoff:
                    continue  # nothing to postpone
                not_before[code] = original[code].start + 1 if later is None else _parse_utc(later)
            case TeamWithdrawn():
                pass

    specs = {m.code: _spec_of(m) for m in [*started, *waiting]}
    grid = [t for t in _grid(policy) if t.start >= cutoff]

    day_opens: dict[int, int] = {}
    for time in grid:
        day_opens.setdefault(time.day, time.start)

    def earliest(code: str, earlier: bool) -> int:
        """A match moves later, or earlier only on a day nobody has started playing yet."""
        match = original[code]
        opens = day_opens.get(match.day - 1)
        if earlier and opens is not None and opens < match.start:
            return max(cutoff, opens)
        return max(cutoff, match.start)

    def attempt(
        release_from: int | None, *, earlier: bool = False
    ) -> tuple[_Planner, list[str], list[ScheduledMatch]]:
        planner = _Planner(specs, policy, blocked)
        for m in started:
            planner.place(m.code, m.start, m.pitch, m.day - 1, end=ends[m.code])
        queue: list[ScheduledMatch] = []
        for m in waiting:
            keep = m.code not in not_before and (release_from is None or m.start < release_from)
            if keep and planner.fits(m.code, m.start, m.pitch, m.day - 1):
                planner.place(m.code, m.start, m.pitch, m.day - 1)
            else:
                queue.append(m)
        moving = {m.together for m in queue} - {None}
        for m in waiting:  # a last round moves as a whole
            if m.together in moving and m.code in planner.placed:
                planner.remove(m.code)
                queue.append(m)
        queue.sort(key=lambda m: (m.start, m.code))
        unplaced: list[str] = []
        for unit in _units([m.code for m in queue], specs):
            lower = max(
                min(earliest(c, earlier) for c in unit),
                max(not_before.get(c, 0) for c in unit),
            )
            prefer = {c: original[c].pitch for c in unit}
            if not planner.place_unit(unit, [t for t in grid if t.start >= lower], prefer):
                unplaced.extend(c for c in unit if c not in planner.placed)
        return planner, unplaced, queue

    planner, unplaced, queue = attempt(None)
    if unplaced:
        release_from = min(m.start for m in queue)
        planner, unplaced, _ = attempt(release_from)
        if unplaced:
            planner, unplaced, _ = attempt(release_from, earlier=True)
    if unplaced:
        raise ScheduleInfeasible(
            f"{len(unplaced)} matches no longer fit ({', '.join(unplaced[:5])})",
            unplaced=unplaced,
            matches=len(specs),
            slots=len(grid) * len(policy.pitches),
        )
    moved = sorted(
        m.code
        for m in waiting
        if (planner.placed[m.code].start, planner.placed[m.code].pitch) != (m.start, m.pitch)
    )
    new_plan, _ = _plan(
        planner,
        policy,
        seed=plan.seed,
        strategy="reschedule",
        walkovers=sorted({*plan.walkovers, *walkovers}),
        moved=moved,
        check_fixed=False,
    )
    return new_plan


# --- relaxations -----------------------------------------------------------------------------


def _widen(day: DayWindow, *, earlier: int = 0, later: int = 0) -> DayWindow:
    start = minute_of_day(day.start) - earlier
    end = minute_of_day(day.end) + later
    return day.model_copy(
        update={"start": dt.time(start // 60, start % 60), "end": dt.time(end // 60, end % 60)}
    )


def suggest_relaxations(
    groups: Sequence[Sequence[str]],
    bracket: Bracket | None,
    policy: SchedulePolicy,
    *,
    seed: bytes,
    group_rounds: Literal[1, 2] = 1,
) -> list[Relaxation]:
    """Concrete changes that would make the schedule fit, feasible ones first.

    Empty when the schedule already fits. Each option is the smallest step of its kind that
    fits (or the largest tried, marked not feasible). Smaller groups change the format and
    come from `engine.format_auto` instead.
    """

    def feasible(candidate: SchedulePolicy) -> bool:
        try:
            build_schedule(groups, bracket, candidate, seed=seed, group_rounds=group_rounds)
        except ScheduleInfeasible:
            return False
        return True

    if feasible(policy):
        return []

    def smallest(kind: str, steps: Iterable[tuple[str, SchedulePolicy]]) -> Relaxation | None:
        last: Relaxation | None = None
        for summary, candidate in steps:
            last = Relaxation(kind, summary, candidate, total_slots(candidate), feasible(candidate))
            if last.feasible:
                break
        return last

    def update(**values: object) -> SchedulePolicy:
        return policy.model_copy(update=values)

    days = policy.days
    starts = [minute_of_day(d.start) for d in days]
    ends = [minute_of_day(d.end) for d in days]
    floor = max(10, policy.match_minutes // 2)
    options: list[Callable[[], Relaxation | None]] = [
        lambda: smallest(
            "add_pitch",
            (
                (
                    f"Add {n} pitch{'es' if n > 1 else ''}",
                    update(pitches=[*policy.pitches, *(f"extra-{i}" for i in range(1, n + 1))]),
                )
                for n in (1, 2)
            ),
        ),
        lambda: smallest(
            "longer_days",
            (
                (
                    f"Start every day {k} minutes earlier",
                    update(days=[_widen(d, earlier=k) for d in days]),
                )
                for k in (30, 60, 90, 120)
                if min(starts) - k >= _EARLIEST_START
            ),
        ),
        lambda: smallest(
            "longer_days",
            (
                (
                    f"End every day {k} minutes later",
                    update(days=[_widen(d, later=k) for d in days]),
                )
                for k in (30, 60, 90, 120)
                if max(ends) + k <= _LATEST_END
            ),
        ),
        lambda: smallest(
            "shorter_matches",
            (
                (f"Shorten matches to {m} minutes of pitch time", update(match_minutes=m))
                for m in range(policy.match_minutes - 5, floor - 1, -5)
            ),
        ),
        lambda: smallest(
            "more_matches_per_day",
            [
                (
                    f"Allow {policy.max_matches_per_team_per_day + 1} matches per team per day",
                    update(max_matches_per_team_per_day=policy.max_matches_per_team_per_day + 1),
                )
            ],
        ),
    ]
    if policy.simultaneous_last_group_round:
        options.append(
            lambda: smallest(
                "last_round_not_together",
                [
                    (
                        "Let the last group matches kick off at different times",
                        update(simultaneous_last_group_round=False),
                    )
                ],
            )
        )
    relaxations = [r for r in (option() for option in options) if r is not None]
    return sorted(relaxations, key=lambda r: not r.feasible)
