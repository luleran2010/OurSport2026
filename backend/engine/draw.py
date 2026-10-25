"""The group draw (docs/04-engine.md "Draw", docs/12-tournament-setup.md §5).

Every valid draw is equally likely. Sequential "skip to the next valid group" drawing is
biased, so instead:

1. Few valid draws (<= `enumeration_limit`): list them all, pick one uniformly.
2. Otherwise: rejection sampling — draw uniformly among assignments that respect pots and
   fixed placements, discard any that break a separation. Accepted draws are uniform.
3. If separations make that too rare: a randomised constraint search; still valid, but
   reported as `uniform=False`.

Randomness comes only from the stored seed (`DeterministicRng`), so the draw is reproducible.
When the rules cannot all hold, `DrawInfeasible` names a minimal set of rules that clash.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from engine.rng import DeterministicRng
from engine.rules.format import FormatSpec, group_letter
from engine.rules.seeding import FixedPlacement, SeedingPolicy, SeedingSource, Separation

DRAW_ALGORITHM = "draw-1"
ENUMERATION_LIMIT = 2000
MAX_REJECTIONS = 20_000

Constraint = Separation | FixedPlacement
DrawMethod = Literal["enumeration", "rejection", "randomized_search"]


@dataclass(frozen=True)
class SeedEntry:
    """A team and the data seeding may use. Lower placement/rank is better; higher rating."""

    team: str
    previous_placement: int | None = None  # last edition: 1 = winner, 2 = runner-up, …
    rating: float | None = None
    organiser_rank: int | None = None  # position in the organiser's own list


@dataclass(frozen=True)
class TeamPlacement:
    """Where a team was drawn and why. Structured, so the app can explain it in any language."""

    team: str
    group_index: int
    group: str  # "A"
    position: int  # 1-based draw position in the group (A1, A2, …)
    pot: int | None  # 1-based; None when the draw has no pots
    seeded_by: SeedingSource  # NONE: unseeded
    seed_value: float | None  # the placement, rating or rank that seeded the team
    fixed: bool
    kept_apart: tuple[str, ...]  # reasons of the separations this team is part of


@dataclass(frozen=True)
class Draw:
    groups: tuple[tuple[str, ...], ...]  # team ids per group, in draw position order
    pots: tuple[tuple[str, ...], ...]  # team ids per pot, best ranked first
    placements: tuple[TeamPlacement, ...]
    seed: bytes
    method: DrawMethod
    uniform: bool  # every valid draw was equally likely
    valid_draws: int | None  # how many valid draws existed (known when enumerated)
    algorithm: str = DRAW_ALGORITHM


class DrawInfeasible(Exception):
    """The draw rules cannot all hold; `conflict` is a minimal set of clashing rules."""

    def __init__(self, conflict: Sequence[Constraint], group_count: int) -> None:
        self.conflict = tuple(conflict)
        super().__init__(_conflict_message(self.conflict, group_count))


def _describe(constraint: Constraint) -> str:
    if isinstance(constraint, FixedPlacement):
        return f"{constraint.team} fixed in group {group_letter(constraint.group_index)}"
    return f"{', '.join(constraint.teams)} kept apart ({constraint.reason})"


def _conflict_message(conflict: tuple[Constraint, ...], group_count: int) -> str:
    if len(conflict) == 1 and isinstance(conflict[0], Separation):
        separation = conflict[0]
        if separation.kind == "distinct_groups":
            return (
                f"{len(separation.teams)} teams ({separation.reason}) must be in different "
                f"groups, but there are only {group_count} groups"
            )
        return (
            f"{len(separation.teams)} teams ({separation.reason}) may have at most "
            f"{separation.max_per_group} per group, but there are only {group_count} groups"
        )
    return "These draw rules cannot all hold together: " + "; ".join(_describe(c) for c in conflict)


# --- ranking and pots ------------------------------------------------------------------------


def _source_value(entry: SeedEntry, source: SeedingSource) -> float | None:
    """A value where lower ranks higher, or None when the team has no data for the source."""
    match source:
        case SeedingSource.PREVIOUS_PLACEMENT:
            return entry.previous_placement
        case SeedingSource.RATING:
            return None if entry.rating is None else -entry.rating
        case SeedingSource.ORGANISER_ORDER:
            return entry.organiser_rank
        case _:
            return None


def _rank(
    entries: Sequence[SeedEntry], policy: SeedingPolicy, rng: DeterministicRng
) -> list[SeedEntry]:
    """Best first by each source in turn; teams without data, and exact ties, in random order."""
    by_id = sorted(entries, key=lambda e: e.team)
    random_order = {e.team: i for i, e in enumerate(rng.shuffled(by_id))}

    def key(entry: SeedEntry) -> tuple[object, ...]:
        parts: list[object] = []
        for source in policy.source:
            value = _source_value(entry, source)
            parts.append((0, value) if value is not None else (1, 0))
        parts.append(random_order[entry.team])
        return tuple(parts)

    return sorted(by_id, key=key)


def _seeded_by(entry: SeedEntry, policy: SeedingPolicy) -> tuple[SeedingSource, float | None]:
    for source in policy.source:
        value = _source_value(entry, source)
        if value is not None:
            shown = -value if source is SeedingSource.RATING else value
            return source, shown
    return SeedingSource.NONE, None


def _pot_sizes(group_sizes: Sequence[int]) -> list[int]:
    """Pot k holds one team for every group with more than k places."""
    return [sum(size > k for size in group_sizes) for k in range(max(group_sizes))]


# --- constraint search -----------------------------------------------------------------------


class _Solver:
    """Depth-first search over team -> group, most constrained team first."""

    def __init__(
        self,
        teams: Sequence[str],
        sizes: Sequence[int],
        pot_of: dict[str, int | None],
        constraints: Sequence[Constraint],
    ) -> None:
        self.teams = list(teams)
        self.sizes = list(sizes)
        self.pot_of = pot_of
        self.fixed = {c.team: c.group_index for c in constraints if isinstance(c, FixedPlacement)}
        self.separations = [c for c in constraints if isinstance(c, Separation)]
        self.limits = [
            1 if s.kind == "distinct_groups" else s.max_per_group for s in self.separations
        ]
        self.member_of: dict[str, list[int]] = {team: [] for team in teams}
        for index, separation in enumerate(self.separations):
            for team in set(separation.teams):
                if team in self.member_of:
                    self.member_of[team].append(index)

    def solutions(self, limit: int, rng: DeterministicRng | None = None) -> list[dict[str, int]]:
        """Up to `limit` complete assignments; with `rng`, explore groups in random order."""
        assignment: dict[str, int] = {}
        filled = [0] * len(self.sizes)
        pot_taken: set[tuple[int, int]] = set()
        separation_count: dict[tuple[int, int], int] = {}
        found: list[dict[str, int]] = []

        def domain(team: str) -> list[int]:
            pot = self.pot_of[team]
            candidates = [self.fixed[team]] if team in self.fixed else range(len(self.sizes))
            return [
                g
                for g in candidates
                if filled[g] < self.sizes[g]
                and (pot is None or (self.sizes[g] > pot and (g, pot) not in pot_taken))
                and all(
                    separation_count.get((i, g), 0) < self.limits[i] for i in self.member_of[team]
                )
            ]

        def search() -> bool:
            unassigned = [t for t in self.teams if t not in assignment]
            if not unassigned:
                found.append(dict(assignment))
                return len(found) >= limit
            best_team, best_domain = "", list[int]()
            for team in unassigned:
                options = domain(team)
                if not options:
                    return False
                if not best_team or len(options) < len(best_domain):
                    best_team, best_domain = team, options
            order = rng.shuffled(best_domain) if rng is not None else best_domain
            pot = self.pot_of[best_team]
            for g in order:
                assignment[best_team] = g
                filled[g] += 1
                if pot is not None:
                    pot_taken.add((g, pot))
                for i in self.member_of[best_team]:
                    separation_count[(i, g)] = separation_count.get((i, g), 0) + 1
                if search():
                    return True
                for i in self.member_of[best_team]:
                    separation_count[(i, g)] -= 1
                if pot is not None:
                    pot_taken.discard((g, pot))
                filled[g] -= 1
                del assignment[best_team]
            return False

        search()
        return found


def _minimal_conflict(
    teams: Sequence[str],
    sizes: Sequence[int],
    pot_of: dict[str, int | None],
    constraints: Sequence[Constraint],
) -> list[Constraint]:
    """Deletion filter: drop every rule whose removal still leaves the rest impossible."""
    core = list(constraints)
    for constraint in list(constraints):
        trial = [c for c in core if c is not constraint]
        if not _Solver(teams, sizes, pot_of, trial).solutions(limit=1):
            core = trial
    return core


# --- sampling --------------------------------------------------------------------------------


def _propose(
    ranked: Sequence[str],
    sizes: Sequence[int],
    pot_of: dict[str, int | None],
    fixed: dict[str, int],
    rng: DeterministicRng,
) -> dict[str, int] | None:
    """Uniform over assignments respecting pots, capacities and fixed placements."""
    assignment = dict(fixed)
    pots = sorted({p for p in pot_of.values() if p is not None})
    if pots:
        for pot in pots:
            members = [t for t in ranked if pot_of[t] == pot]
            taken = {fixed[t] for t in members if t in fixed}
            if any(sizes[g] <= pot for g in taken):
                return None
            free = [g for g in range(len(sizes)) if sizes[g] > pot and g not in taken]
            movers = [t for t in members if t not in fixed]
            if len(free) != len(movers):
                return None
            assignment.update(zip(rng.shuffled(movers), free, strict=True))
        return assignment
    remaining = list(sizes)
    for g in fixed.values():
        remaining[g] -= 1
    if min(remaining) < 0:
        return None
    slots = [g for g, count in enumerate(remaining) for _ in range(count)]
    movers = [t for t in ranked if t not in fixed]
    assignment.update(zip(rng.shuffled(movers), slots, strict=True))
    return assignment


def _respects(assignment: dict[str, int], separations: Sequence[Separation]) -> bool:
    for separation in separations:
        limit = 1 if separation.kind == "distinct_groups" else separation.max_per_group
        counts: dict[int, int] = {}
        for team in separation.teams:
            g = assignment[team]
            counts[g] = counts.get(g, 0) + 1
            if counts[g] > limit:
                return False
    return True


# --- the draw --------------------------------------------------------------------------------


def make_draw(
    teams: Sequence[SeedEntry],
    fmt: FormatSpec,
    policy: SeedingPolicy,
    *,
    seed: bytes,
    enumeration_limit: int = ENUMERATION_LIMIT,
    max_rejections: int = MAX_REJECTIONS,
) -> Draw:
    """Draw `teams` into the groups of `fmt` under `policy`, reproducibly from `seed`."""
    if not fmt.group_sizes:
        raise ValueError("a draw needs groups; this format has none")
    ids = [entry.team for entry in teams]
    if len(set(ids)) != len(ids):
        raise ValueError("a team is listed twice")
    if len(ids) != fmt.team_count or sum(fmt.group_sizes) != fmt.team_count:
        raise ValueError(f"the format holds {fmt.team_count} teams, but {len(ids)} were given")

    rng = DeterministicRng(seed)
    ranked_entries = _rank(teams, policy, rng)
    ranked = [entry.team for entry in ranked_entries]
    sizes = fmt.group_sizes

    pot_of: dict[str, int | None]
    pots: list[list[str]]
    if policy.pots == "by_group_position":
        pots, start = [], 0
        for size in _pot_sizes(sizes):
            pots.append(ranked[start : start + size])
            start += size
        pot_of = {team: k for k, pot in enumerate(pots) for team in pot}
    else:
        pots = [ranked]
        pot_of = dict.fromkeys(ranked)

    constraints: list[Constraint] = [*policy.separations, *policy.fixed]
    solver = _Solver(ranked, sizes, pot_of, constraints)
    enumerated = solver.solutions(limit=enumeration_limit + 1)
    if not enumerated:
        raise DrawInfeasible(_minimal_conflict(ranked, sizes, pot_of, constraints), len(sizes))

    method: DrawMethod
    if len(enumerated) <= enumeration_limit:
        assignment = enumerated[rng.randbelow(len(enumerated))]
        method, uniform, valid_draws = "enumeration", True, len(enumerated)
    else:
        valid_draws = None
        fixed = {c.team: c.group_index for c in policy.fixed}
        accepted = None
        for _ in range(max_rejections):
            proposal = _propose(ranked, sizes, pot_of, fixed, rng)
            if proposal is not None and _respects(proposal, policy.separations):
                accepted = proposal
                break
        if accepted is not None:
            assignment, method, uniform = accepted, "rejection", True
        else:
            assignment = solver.solutions(limit=1, rng=rng)[0]
            method, uniform = "randomized_search", False

    groups = _positions(assignment, ranked, pot_of, len(sizes), policy.fixed)
    return Draw(
        groups=groups,
        pots=tuple(tuple(pot) for pot in pots) if policy.pots == "by_group_position" else (),
        placements=_placements(groups, ranked_entries, pot_of, policy),
        seed=seed,
        method=method,
        uniform=uniform,
        valid_draws=valid_draws,
    )


def _positions(
    assignment: dict[str, int],
    ranked: Sequence[str],
    pot_of: dict[str, int | None],
    group_count: int,
    fixed: Sequence[FixedPlacement],
) -> tuple[tuple[str, ...], ...]:
    """Order each group by pot (or rank); then honour fixed draw positions (e.g. host = A1)."""
    rank = {team: i for i, team in enumerate(ranked)}
    groups = [
        sorted(
            (t for t in ranked if assignment[t] == g),
            key=lambda t: (pot_of[t] if pot_of[t] is not None else 0, rank[t]),
        )
        for g in range(group_count)
    ]
    for placement in fixed:
        if placement.position_in_group is None:
            continue
        members = groups[placement.group_index]
        here, target = members.index(placement.team), placement.position_in_group - 1
        if target < len(members):
            members[here], members[target] = members[target], members[here]
    return tuple(tuple(members) for members in groups)


def _placements(
    groups: tuple[tuple[str, ...], ...],
    ranked_entries: Sequence[SeedEntry],
    pot_of: dict[str, int | None],
    policy: SeedingPolicy,
) -> tuple[TeamPlacement, ...]:
    entry_of = {entry.team: entry for entry in ranked_entries}
    fixed = {placement.team for placement in policy.fixed}
    placements = []
    for g, members in enumerate(groups):
        for position, team in enumerate(members, start=1):
            source, value = _seeded_by(entry_of[team], policy)
            pot = pot_of[team]
            placements.append(
                TeamPlacement(
                    team=team,
                    group_index=g,
                    group=group_letter(g),
                    position=position,
                    pot=None if pot is None else pot + 1,
                    seeded_by=source,
                    seed_value=value,
                    fixed=team in fixed,
                    kept_apart=tuple(s.reason for s in policy.separations if team in s.teams),
                )
            )
    return tuple(placements)
