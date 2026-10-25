"""Which other matches matter to a team (docs/04-engine.md, Relevance).

For each remaining match the team is not in, the share of completions in which the team
goes through is computed for each outcome of that match (from the scenario enumeration);
the impact is the largest minus the smallest share. Matches that cannot affect the team
(another group, no best-of-the-rest places) have impact 0 and come last.
"""

from dataclasses import dataclass

from engine.model import TournamentState
from engine.scenarios import MAX_BRANCHES, Condition, Side, outcome_table


@dataclass(frozen=True)
class OutcomeShare:
    outcome: Side
    winner: str | None
    share: float  # of completions in which the team goes through, given this outcome


@dataclass(frozen=True)
class RelevanceItem:
    match_id: str
    impact: float  # 0..1
    shares: tuple[OutcomeShare, ...]  # empty when the match cannot affect the team
    best_outcome: Side | None  # the outcome that helps the team most
    reason: str  # plain language, names from the state


def _describe(condition: Condition, names: dict[str, str]) -> str:
    if condition.outcome == "draw" or condition.winner is None:
        return "a draw"
    return f"a {names.get(condition.winner, condition.winner)} win"


def match_relevance(
    state: TournamentState, team: str, *, max_branches: int = MAX_BRANCHES
) -> list[RelevanceItem]:
    """Remaining matches without `team`, most relevant to it first."""
    names = {t.id: t.name for t in state.teams}
    fixtures, conditions, completions = outcome_table(state, team, max_branches=max_branches)
    index = {f.match_id: i for i, f in enumerate(fixtures)}
    items: list[tuple[str, RelevanceItem]] = []
    for fixture in state.fixtures:
        if team in (fixture.home, fixture.away):
            continue
        position = index.get(fixture.match_id)
        if position is None:
            item = RelevanceItem(
                fixture.match_id, 0.0, (), None, f"Does not affect {names.get(team, team)}."
            )
            items.append((fixture.starts_at, item))
            continue
        shares = []
        for choice, condition in enumerate(conditions[position]):
            values = [value for choices, value in completions if choices[position] == choice]
            share = sum(values) / len(values) if values else 0.0
            shares.append(OutcomeShare(condition.outcome, condition.winner, share))
        best = max(range(len(shares)), key=lambda i: shares[i].share)
        worst = min(range(len(shares)), key=lambda i: shares[i].share)
        impact = shares[best].share - shares[worst].share
        reason = (
            f"Best for {names.get(team, team)}: {_describe(conditions[position][best], names)}; "
            f"worst: {_describe(conditions[position][worst], names)}."
            if impact > 0
            else f"Does not change {names.get(team, team)}'s chances."
        )
        item = RelevanceItem(
            fixture.match_id,
            round(impact, 6),
            tuple(shares),
            shares[best].outcome if impact > 0 else None,
            reason,
        )
        items.append((fixture.starts_at, item))
    items.sort(key=lambda pair: (-pair[1].impact, pair[0], pair[1].match_id))
    return [item for _, item in items]
