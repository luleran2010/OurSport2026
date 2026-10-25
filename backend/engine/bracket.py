"""Knockout brackets: building them and filling their placeholders (docs/04-engine.md).

Building (`build_bracket`):
- two per group: World Cup pattern (A1-B2, C1-D2 | B1-A2, D1-C2), so teams of the same
  group can meet again only in the final;
- one per group: neighbouring groups (A1-B1, C1-D1);
- with best-of-the-rest qualifiers: winners face them first, then runners-up; the pairs are
  split into halves keeping teams of the same group apart where possible;
- a single group, other shapes and pure knockouts: standard seeding (1 v 8, 4 v 5, …);
- `crossover="custom"`: the organiser's pairs, as given.

Resolving (`resolve_bracket`): a slot is filled only once it can no longer change — the
group is finished and the place decided, or points bounds leave a single possible team. Until
then it lists who could still take it. A tie only lots can break blocks the slot.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, permutations
from typing import Literal

from engine.model import MatchResult, TournamentState
from engine.rules.config import AdvancementRule
from engine.rules.format import (
    THIRD_PLACE_CODE,
    FormatSpec,
    KnockoutRound,
    best_rest_source,
    group_letter,
    group_source,
    loser_source,
    round_match_codes,
    winner_source,
)
from engine.sports.registry import get_sport
from engine.standings import GroupStandings, StandingRow, Standings, compute_standings

BracketRound = KnockoutRound | Literal["third_place"]
SlotStatus = Literal["resolved", "pending", "blocked"]


@dataclass(frozen=True)
class BracketMatch:
    code: str  # "QF1", "3P", "F"
    round: BracketRound
    home_source: str
    away_source: str


@dataclass(frozen=True)
class Bracket:
    matches: tuple[BracketMatch, ...]  # in playing order: first round … third place, final


@dataclass(frozen=True)
class SlotResolution:
    source: str
    status: SlotStatus
    team: str | None  # set when resolved
    could_be: tuple[str, ...]  # teams that can still fill the slot (pending or blocked)
    blocked_reason: str | None = None  # "draw_lots"


@dataclass(frozen=True)
class MatchResolution:
    code: str
    round: BracketRound
    home: SlotResolution
    away: SlotResolution


@dataclass(frozen=True)
class BracketResolution:
    matches: tuple[MatchResolution, ...]


# --- building --------------------------------------------------------------------------------


def _seed_order(size: int) -> list[int]:
    """Standard seeded bracket positions: 1, 8, 4, 5, 2, 7, 3, 6 for eight."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [seed for s in order for seed in (s, total - s)]
    return order


def _seeded_pairs(sources: Sequence[str]) -> list[tuple[str, str]]:
    order = _seed_order(len(sources))
    return [(sources[order[i] - 1], sources[order[i + 1] - 1]) for i in range(0, len(order), 2)]


def _group_of(source: str) -> str | None:
    parts = source.split(":")
    return parts[1] if parts[0] == "group" else None


def _conflicts(pairs: Sequence[tuple[str, str]]) -> int:
    counts = Counter(g for pair in pairs for s in pair if (g := _group_of(s)) is not None)
    return sum(n * (n - 1) // 2 for n in counts.values())


def _arrange(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Order first-round pairs so each half keeps teams of the same group apart."""
    if len(pairs) <= 2:
        return list(pairs)
    half = len(pairs) // 2
    best: tuple[int, list[int]] | None = None
    for rest in combinations(range(1, len(pairs)), half - 1):
        top = [0, *rest]
        bottom = [i for i in range(len(pairs)) if i not in top]
        score = _conflicts([pairs[i] for i in top]) + _conflicts([pairs[i] for i in bottom])
        if best is None or score < best[0]:
            best = (score, top)
    assert best is not None
    top = best[1]
    bottom = [i for i in range(len(pairs)) if i not in top]
    return _arrange([pairs[i] for i in top]) + _arrange([pairs[i] for i in bottom])


def _pair_greedily(sources: list[str]) -> list[tuple[str, str]]:
    """Pair in order, each with the next source from a different group when there is one."""
    pairs = []
    while sources:
        first = sources.pop(0)
        index = next(
            (
                i
                for i, s in enumerate(sources)
                if _group_of(s) != _group_of(first) or _group_of(s) is None
            ),
            0,
        )
        pairs.append((first, sources.pop(index)))
    return pairs


def _mixed_pairs(letters: Sequence[str], advancement: AdvancementRule) -> list[tuple[str, str]]:
    """Winners face best-of-the-rest qualifiers first, then lower-placed teams of other groups."""
    winners = [group_source(letter, 1) for letter in letters]
    others = [
        group_source(letter, position)
        for position in range(2, advancement.per_group + 1)
        for letter in letters
    ]
    rest = [best_rest_source(rank) for rank in range(1, advancement.best_of_rest + 1)]
    pairs = [(winners.pop(0), rest.pop(0)) for _ in range(min(len(winners), len(rest)))]
    for winner in list(winners):
        if not others:
            break
        index = letters.index(_group_of(winner) or "")
        partner = letters[index ^ 1] if index ^ 1 < len(letters) else None
        choice = next(
            (s for s in others if _group_of(s) == partner),
            next((s for s in others if _group_of(s) != _group_of(winner)), others[0]),
        )
        others.remove(choice)
        winners.remove(winner)
        pairs.append((winner, choice))
    return _arrange(pairs + _pair_greedily(winners + others + rest))


def _first_round(fmt: FormatSpec, advancement: AdvancementRule) -> list[tuple[str, str]]:
    assert fmt.knockout is not None
    if fmt.knockout.crossover == "custom":
        return list(fmt.knockout.custom_pairs)
    if not fmt.group_sizes:
        return _seeded_pairs([f"seed:{i}" for i in range(1, fmt.team_count + 1)])
    letters = fmt.group_letters
    per_group, best_of_rest = advancement.per_group, advancement.best_of_rest
    if best_of_rest:
        return _mixed_pairs(letters, advancement)
    if len(letters) > 1 and per_group == 1:
        return [
            (group_source(a, 1), group_source(b, 1))
            for a, b in zip(letters[::2], letters[1::2], strict=True)
        ]
    if len(letters) > 1 and per_group == 2:
        top = [
            (group_source(a, 1), group_source(b, 2))
            for a, b in zip(letters[::2], letters[1::2], strict=True)
        ]
        bottom = [
            (group_source(b, 1), group_source(a, 2))
            for a, b in zip(letters[::2], letters[1::2], strict=True)
        ]
        return top + bottom
    seeds = [group_source(letter, p) for p in range(1, per_group + 1) for letter in letters]
    return _seeded_pairs(seeds)


def build_bracket(fmt: FormatSpec, advancement: AdvancementRule) -> Bracket:
    """All knockout matches with placeholder sources, in playing order."""
    if fmt.knockout is None:
        raise ValueError("this format has no knockout")
    rounds = fmt.knockout.rounds
    pairs = _first_round(fmt, advancement)
    matches: list[BracketMatch] = []
    previous: list[str] = []
    for index, round_ in enumerate(rounds):
        codes = round_match_codes(round_)
        if index == 0:
            sources = pairs
        else:
            sources = [
                (winner_source(previous[2 * j]), winner_source(previous[2 * j + 1]))
                for j in range(len(codes))
            ]
        if round_ == "final" and fmt.knockout.third_place_match and len(previous) == 2:
            matches.append(
                BracketMatch(
                    THIRD_PLACE_CODE,
                    "third_place",
                    loser_source(previous[0]),
                    loser_source(previous[1]),
                )
            )
        matches.extend(
            BracketMatch(code, round_, home, away)
            for code, (home, away) in zip(codes, sources, strict=True)
        )
        previous = codes
    return Bracket(matches=tuple(matches))


# --- resolving -------------------------------------------------------------------------------


def _resolved(source: str, team: str) -> SlotResolution:
    return SlotResolution(source, "resolved", team, ())


class _Resolver:
    def __init__(
        self,
        bracket: Bracket,
        state: TournamentState,
        knockout_results: Mapping[str, MatchResult],
        seeds: Mapping[str, str],
    ) -> None:
        self.bracket = bracket
        self.state = state
        self.knockout_results = knockout_results
        self.seeds = seeds
        self.sport = get_sport(state.rules.sport)
        self.standings: Standings = compute_standings(state)
        group_ids = list(state.groups)
        self.group_by_letter: dict[str, GroupStandings] = {
            group_letter(i): self.standings.groups[i] for i in range(len(group_ids))
        }
        self.letter_of_team = {
            team: group_letter(i) for i, gid in enumerate(group_ids) for team in state.groups[gid]
        }
        self.remaining = Counter(
            team
            for fixture in state.fixtures
            if fixture.group_id is not None
            for team in (fixture.home, fixture.away)
            if team is not None
        )
        self.open_groups = {f.group_id for f in state.fixtures if f.group_id is not None}
        table = state.rules.points.table
        self.max_points, self.min_points = max(table.values()), min(table.values())
        self.by_code: dict[str, MatchResolution] = {}
        self.rest_slots: dict[str, SlotResolution] = {}

    def resolve(self) -> BracketResolution:
        for match in self.bracket.matches:
            self.by_code[match.code] = MatchResolution(
                match.code, match.round, self.slot(match.home_source), self.slot(match.away_source)
            )
        return BracketResolution(tuple(self.by_code[m.code] for m in self.bracket.matches))

    def slot(self, source: str) -> SlotResolution:
        kind = source.split(":")[0]
        if kind == "group":
            _, letter, position = source.split(":")
            return self._group_slot(source, letter, int(position))
        if kind == "best_rest":
            return self._rest_slot(source)
        if kind in ("winner", "loser"):
            return self._match_slot(source, kind, source.split(":", 1)[1])
        if kind == "seed":
            team = self.seeds.get(source)
            return _resolved(source, team) if team else SlotResolution(source, "pending", None, ())
        raise ValueError(f"unknown placeholder '{source}'")

    # groups

    def _group_finished(self, group: GroupStandings) -> bool:
        return group.group_id not in self.open_groups

    def _candidates(self, group: GroupStandings, position: int) -> list[str]:
        """Teams that can still finish at `position`, from points bounds (never too few)."""
        rows = group.rows
        low = {r.team: r.stats.points + self.remaining[r.team] * self.min_points for r in rows}
        high = {r.team: r.stats.points + self.remaining[r.team] * self.max_points for r in rows}
        candidates = []
        for row in rows:
            t = row.team
            surely_above = sum(1 for u in rows if u.team != t and low[u.team] > high[t])
            surely_below = sum(1 for u in rows if u.team != t and high[u.team] < low[t])
            if surely_above < position and surely_below <= len(rows) - position:
                candidates.append(t)
        return candidates

    def _group_slot(self, source: str, letter: str, position: int) -> SlotResolution:
        group = self.group_by_letter.get(letter)
        if group is None or position > len(group.rows):
            raise ValueError(f"'{source}' does not exist in this tournament")
        if self._group_finished(group):
            block = _tie_block(group.rows, position)
            if len(block) == 1:
                return _resolved(source, block[0].team)
            return SlotResolution(
                source, "blocked", None, tuple(r.team for r in block), blocked_reason="draw_lots"
            )
        candidates = self._candidates(group, position)
        if len(candidates) == 1:
            return _resolved(source, candidates[0])
        return SlotResolution(source, "pending", None, tuple(candidates))

    def _rest_slot(self, source: str) -> SlotResolution:
        if not self.rest_slots:
            self.rest_slots = self._resolve_rest()
        return self.rest_slots.get(source, SlotResolution(source, "pending", None, ()))

    def _resolve_rest(self) -> dict[str, SlotResolution]:
        advancement = self.state.rules.advancement
        count = advancement.best_of_rest
        sources = [best_rest_source(k) for k in range(1, count + 1)]
        position = advancement.per_group + 1
        if any(not self._group_finished(g) for g in self.standings.groups):
            could_be = tuple(
                team
                for g in self.standings.groups
                if len(g.rows) >= position
                for team in self._candidates(g, position)
            )
            return {s: SlotResolution(s, "pending", None, could_be) for s in sources}
        rest = self.standings.rest
        qualifying = rest[:count]
        # A tie among the qualifiers (or across the cut-off) needs lots before slots fill.
        if any(r.tied_unresolved for r in qualifying):
            tied = tuple(r.team for r in rest if r.tied_unresolved or r in qualifying)
            return {
                s: SlotResolution(s, "blocked", None, tied, blocked_reason="draw_lots")
                for s in sources
            }
        teams = self._avoid_own_group([r.team for r in qualifying], sources)
        return {s: _resolved(s, t) for s, t in zip(sources, teams, strict=True)}

    def _avoid_own_group(self, teams: list[str], sources: list[str]) -> list[str]:
        """Swap best-of-the-rest teams so none faces the winner of its own group, if possible."""
        opponent_group = {}
        for match in self.bracket.matches:
            for mine, theirs in (
                (match.home_source, match.away_source),
                (match.away_source, match.home_source),
            ):
                if mine in sources:
                    opponent_group[mine] = _group_of(theirs)
        for candidate in permutations(teams):
            if all(
                self.letter_of_team.get(team) != opponent_group.get(source)
                for team, source in zip(candidate, sources, strict=True)
            ):
                return list(candidate)
        return teams

    # knockout

    def _match_slot(self, source: str, kind: str, code: str) -> SlotResolution:
        earlier = self.by_code.get(code)
        result = self.knockout_results.get(code)
        if result is not None:
            winner = self.sport.knockout_winner(result)
            loser = result.away if winner == result.home else result.home
            return _resolved(source, winner if kind == "winner" else loser)
        if earlier is None:
            raise ValueError(f"'{source}' refers to a match that is not earlier in the bracket")
        could_be = tuple(
            team
            for side in (earlier.home, earlier.away)
            for team in ((side.team,) if side.team else side.could_be)
        )
        return SlotResolution(source, "pending", None, could_be)


def _tie_block(rows: Sequence[StandingRow], position: int) -> list[StandingRow]:
    """The rows sharing the place that covers `position` (one row unless tied)."""
    for row in rows:
        block = [r for r in rows if r.position == row.position]
        if row.position <= position < row.position + len(block):
            return block
    return []


def resolve_bracket(
    bracket: Bracket,
    state: TournamentState,
    *,
    knockout_results: Mapping[str, MatchResult] | None = None,
    seeds: Mapping[str, str] | None = None,
) -> BracketResolution:
    """Fill every placeholder that can no longer change.

    `state.fixtures` must list every group match still to play, and `state.groups` must be
    in the format's group order (A, B, …). `knockout_results` are keyed by match code;
    `seeds` maps `seed:k` to teams for pure knockouts.
    """
    return _Resolver(bracket, state, knockout_results or {}, seeds or {}).resolve()
