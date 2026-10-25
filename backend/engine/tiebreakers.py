"""Ranking teams by an ordered list of tiebreakers (docs/04-engine.md, "Standings").

Head-to-head tiebreakers are computed on a mini-table of only the matches between the teams
still tied. With `head_to_head_reapply`, when a head-to-head step separates some teams but
leaves others level, the ranking restarts from the top for just those teams (UEFA style).
Teams nothing separates share a position and are reported as unresolved: the engine never
invents an order, and drawing lots is left to the organiser.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from engine.model import MatchResult, TeamStats
from engine.rules.config import HEAD_TO_HEAD, RuleConfig, Tiebreaker
from engine.sports.base import SportModule

# The overall metric each head-to-head tiebreaker uses on the mini-table.
_MINI_TABLE_METRIC = {
    Tiebreaker.HEAD_TO_HEAD_POINTS: Tiebreaker.POINTS,
    Tiebreaker.HEAD_TO_HEAD_DIFF: Tiebreaker.SCORE_DIFF,
    Tiebreaker.HEAD_TO_HEAD_FOR: Tiebreaker.SCORE_FOR,
}


@dataclass(frozen=True)
class RankedTeam:
    team: str
    position: int  # shared by teams tied_unresolved
    decided_by: Tiebreaker | None  # the tiebreaker that gave the team its own place
    tiebreak_value: float | None  # the team's value on that tiebreaker
    tied_unresolved: bool


@dataclass(frozen=True)
class _Bucket:
    teams: tuple[str, ...]
    decided_by: Tiebreaker | None
    value: float | None
    unresolved: bool


class _Ranker:
    def __init__(
        self,
        results: Sequence[MatchResult],
        rules: RuleConfig,
        sport: SportModule,
        tiebreakers: Sequence[Tiebreaker],
        stats: Mapping[str, TeamStats],
        lots: Sequence[str] = (),
    ) -> None:
        self.lots = list(lots)
        self.results = results
        self.rules = rules
        self.sport = sport
        self.tiebreakers = tiebreakers
        self.stats = stats
        self._mini_tables: dict[frozenset[str], dict[str, TeamStats]] = {}

    def metric(self, tiebreaker: Tiebreaker, team: str, h2h_set: frozenset[str]) -> float | None:
        base = _MINI_TABLE_METRIC.get(tiebreaker)
        if base is None:
            return self.sport.metric(tiebreaker, self.stats[team])
        return self.sport.metric(base, self._mini_table(h2h_set)[team])

    def _mini_table(self, teams: frozenset[str]) -> dict[str, TeamStats]:
        if teams not in self._mini_tables:
            mutual = [r for r in self.results if r.home in teams and r.away in teams]
            self._mini_tables[teams] = {
                team: self.sport.team_stats(mutual, team, self.rules) for team in teams
            }
        return self._mini_tables[teams]

    def order(self, teams: tuple[str, ...], start: int, h2h_set: frozenset[str]) -> list[_Bucket]:
        if len(teams) == 1:
            return [_Bucket(teams, None, None, unresolved=False)]
        for index in range(start, len(self.tiebreakers)):
            tiebreaker = self.tiebreakers[index]
            if tiebreaker is Tiebreaker.DRAW_LOTS:
                # Lots are drawn by the organiser, never by the engine: a recorded order that
                # covers every tied team decides; otherwise the tie stays open.
                if set(teams) <= set(self.lots):
                    drawn = sorted(teams, key=self.lots.index)
                    return [_Bucket((t,), tiebreaker, None, unresolved=False) for t in drawn]
                break
            values = {team: self.metric(tiebreaker, team, h2h_set) for team in teams}
            if any(value is None for value in values.values()):
                continue
            distinct = sorted({v for v in values.values() if v is not None}, reverse=True)
            if len(distinct) == 1:
                continue
            buckets: list[_Bucket] = []
            for value in distinct:
                tied = tuple(team for team in teams if values[team] == value)
                if len(tied) == 1:
                    buckets.append(_Bucket(tied, tiebreaker, value, unresolved=False))
                elif tiebreaker in HEAD_TO_HEAD and self.rules.head_to_head_reapply:
                    buckets.extend(self.order(tied, 0, frozenset(tied)))
                else:
                    # A head-to-head split without re-application keeps the original
                    # mini-table; any other split starts a new one for the teams still tied.
                    next_h2h = h2h_set if tiebreaker in HEAD_TO_HEAD else frozenset(tied)
                    buckets.extend(self.order(tied, index + 1, next_h2h))
            return buckets
        return [_Bucket(teams, None, None, unresolved=True)]


def rank_teams(
    teams: Sequence[str],
    results: Sequence[MatchResult],
    rules: RuleConfig,
    sport: SportModule,
    *,
    tiebreakers: Sequence[Tiebreaker] | None = None,
    stats: Mapping[str, TeamStats] | None = None,
    lots: Sequence[str] = (),
) -> list[RankedTeam]:
    """Rank `teams` on `results` by `tiebreakers` (default: the rule config's).

    `stats` may supply precomputed overall stats (e.g. ranking third-placed teams of
    different groups by their own group records); `lots` is the organiser's drawn order.
    """
    ordered_tiebreakers = list(rules.tiebreakers if tiebreakers is None else tiebreakers)
    overall = (
        dict(stats)
        if stats is not None
        else {team: sport.team_stats(results, team, rules) for team in teams}
    )
    ranker = _Ranker(results, rules, sport, ordered_tiebreakers, overall, lots)
    by_id = tuple(sorted(teams))  # input order must never influence the result
    buckets = ranker.order(by_id, 0, frozenset(by_id))

    ranked: list[RankedTeam] = []
    for bucket in buckets:
        position = len(ranked) + 1
        for team in bucket.teams:
            ranked.append(
                RankedTeam(
                    team=team,
                    position=position,
                    decided_by=bucket.decided_by,
                    tiebreak_value=bucket.value,
                    tied_unresolved=bucket.unresolved,
                )
            )
    return ranked
