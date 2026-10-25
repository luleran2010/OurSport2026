"""Group tables and the cross-group ranking of the best of the rest (docs/04-engine.md)."""

from collections.abc import Sequence
from dataclasses import dataclass

from engine.model import MatchResult, TeamStats, TournamentState
from engine.rules.config import Tiebreaker
from engine.sports.base import SportModule
from engine.sports.registry import get_sport
from engine.tiebreakers import rank_teams

FORM_LENGTH = 5
_FORM_LETTER = {"win": "W", "draw": "D", "loss": "L"}


@dataclass(frozen=True)
class StandingRow:
    position: int  # shared by teams tied_unresolved
    team: str
    stats: TeamStats
    form: tuple[str, ...]  # last results, oldest first: ("W", "D", "L", …)
    decided_by: Tiebreaker | None  # which tiebreaker gave the team its own place
    tiebreak_value: float | None
    tied_unresolved: bool


@dataclass(frozen=True)
class GroupStandings:
    group_id: str | None
    rows: tuple[StandingRow, ...]


@dataclass(frozen=True)
class Standings:
    groups: tuple[GroupStandings, ...]
    rest: tuple[StandingRow, ...]  # best of the rest (e.g. third-placed teams), ranked
    visible: bool  # False when the rules hide tables (youngest age groups)


def compute_standings(state: TournamentState) -> Standings:
    """Tables for every group from its group results only (knockout results never count)."""
    sport = get_sport(state.rules.sport)
    groups = tuple(
        _group_standings(group_id, members, state, sport)
        for group_id, members in state.groups.items()
    )
    return Standings(
        groups=groups, rest=_rest(groups, state, sport), visible=state.rules.standings_visible
    )


def _group_results(
    group_id: str | None, members: Sequence[str], results: Sequence[MatchResult]
) -> list[MatchResult]:
    teams = set(members)
    return [r for r in results if r.group_id == group_id and r.home in teams and r.away in teams]


def _group_standings(
    group_id: str | None, members: Sequence[str], state: TournamentState, sport: SportModule
) -> GroupStandings:
    results = _group_results(group_id, members, state.results)
    stats = {team: sport.team_stats(results, team, state.rules) for team in members}
    lots = state.lots.get(group_id, ())
    ranked = rank_teams(members, results, state.rules, sport, stats=stats, lots=lots)
    rows = tuple(
        StandingRow(
            position=entry.position,
            team=entry.team,
            stats=stats[entry.team],
            form=_form(entry.team, results, sport),
            decided_by=entry.decided_by,
            tiebreak_value=entry.tiebreak_value,
            tied_unresolved=entry.tied_unresolved,
        )
        for entry in ranked
    )
    return GroupStandings(group_id=group_id, rows=rows)


def _form(team: str, results: Sequence[MatchResult], sport: SportModule) -> tuple[str, ...]:
    played = sorted(
        (r for r in results if team in (r.home, r.away)), key=lambda r: (r.starts_at, r.match_id)
    )
    letters = []
    for result in played[-FORM_LENGTH:]:
        key = sport.outcome_key(result, team)
        letters.append(_FORM_LETTER.get(key, key[:1].upper()))
    return tuple(letters)


def _rest(
    groups: Sequence[GroupStandings], state: TournamentState, sport: SportModule
) -> tuple[StandingRow, ...]:
    """Rank the team just below the automatic places in each group, across groups."""
    advancement = state.rules.advancement
    if advancement.best_of_rest == 0:
        return ()
    candidates = {
        group.rows[advancement.per_group].team: group.rows[advancement.per_group]
        for group in groups
        if len(group.rows) > advancement.per_group
    }
    ranked = rank_teams(
        list(candidates),
        state.results,
        state.rules,
        sport,
        tiebreakers=advancement.rest_ranking,
        stats={team: row.stats for team, row in candidates.items()},
    )
    return tuple(
        StandingRow(
            position=entry.position,
            team=entry.team,
            stats=candidates[entry.team].stats,
            form=candidates[entry.team].form,
            decided_by=entry.decided_by,
            tiebreak_value=entry.tiebreak_value,
            tied_unresolved=entry.tied_unresolved,
        )
        for entry in ranked
    )
