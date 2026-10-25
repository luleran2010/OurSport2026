import itertools
import time
from collections.abc import Mapping, Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.bracket import build_bracket
from engine.model import Fixture, MatchResult, TeamRef, TournamentState
from engine.relevance import match_relevance
from engine.rules.format import FormatChoice, groups_then_knockout
from engine.rules.presets import football_rules
from engine.scenarios import Condition, Scenario, compute_scenarios
from engine.sports.football import FootballResult
from engine.standings import compute_standings

TOP_TWO = groups_then_knockout([4, 4], per_group=2)
SIXTEEN = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)
LATER = "2026-06-13T10:00:00Z"


def g(group: str, home: str, away: str, hg: int, ag: int) -> MatchResult:
    return MatchResult(f"{group}:{home}-{away}", group, home, away, FootballResult(hg, ag))


def fx(group: str, home: str, away: str, starts_at: str = LATER) -> Fixture:
    return Fixture(f"{group}:{home}-{away}", group, home, away, starts_at=starts_at)


def make_state(
    groups: Mapping[str | None, tuple[str, ...]],
    results: Sequence[MatchResult],
    fixtures: Sequence[Fixture],
    choice: FormatChoice = TOP_TWO,
) -> TournamentState:
    teams = [t for members in groups.values() for t in members]
    return TournamentState(
        teams=tuple(TeamRef(t, t.upper()) for t in teams),
        groups=groups,
        results=tuple(results),
        fixtures=tuple(fixtures),
        rules=football_rules("football_gd_first", choice),
        format=choice.format,
    )


def last_round() -> TournamentState:
    """a3 6 pts, a1 3, a2 1, a4 1; to play: a1-a4, a2-a3 (group B finished)."""
    group_a = [g("A", "a1", "a2", 1, 0), g("A", "a3", "a4", 1, 0)]
    group_a += [g("A", "a3", "a1", 1, 0), g("A", "a2", "a4", 0, 0)]
    group_b = [g("B", h, a, 1, 0) for h, a in itertools.combinations(("b1", "b2", "b3", "b4"), 2)][
        :5
    ]
    return make_state(
        {"A": ("a1", "a2", "a3", "a4"), "B": ("b1", "b2", "b3", "b4")},
        group_a + group_b,
        [fx("A", "a1", "a4"), fx("A", "a2", "a3"), fx("B", "b3", "b4")],
    )


def path(scenario: Scenario, outcome: str) -> tuple[str, tuple[Condition, ...]]:
    found = next(p for p in scenario.paths if p.outcome == outcome)
    return found.result, found.unless


# --- classification and paths ----------------------------------------------------------------


def test_a_draw_is_enough_unless_the_rival_wins_by_two() -> None:
    scenario = compute_scenarios(last_round(), "a1")

    assert scenario.status == "in_control"
    assert scenario.exact
    assert path(scenario, "win") == ("through", ())
    assert path(scenario, "draw") == (
        "through",
        (Condition("A:a2-a3", "home", "a2", min_margin=2),),
    )
    assert path(scenario, "loss") == ("out", ())
    draw = next(p for p in scenario.paths if p.outcome == "draw")
    assert draw.summary == "Draw: through unless A2 beat A3 by 2 or more."


def test_must_win_and_clinched() -> None:
    state = last_round()

    assert compute_scenarios(state, "a2").status == "must_win"
    assert compute_scenarios(state, "a3").status == "clinched"


def test_finished_group_is_decided_by_the_table() -> None:
    state = last_round()

    assert compute_scenarios(state, "b1").status == "clinched"
    assert compute_scenarios(state, "b4").status == "eliminated"
    done = make_state(
        {"A": ("a1", "a2", "a3", "a4")},
        [g("A", h, a, 2, 0) for h, a in itertools.combinations(("a1", "a2", "a3", "a4"), 2)],
        [],
    )
    assert compute_scenarios(done, "a3").status == "eliminated"
    assert compute_scenarios(done, "a2").status == "clinched"


def test_too_many_branches_fall_back_to_sampling_with_safe_bounds() -> None:
    scenario = compute_scenarios(last_round(), "a3", max_branches=2)

    assert not scenario.exact
    assert scenario.status == "clinched"  # from points bounds, which never mislead
    assert 0 <= scenario.qualify_share <= 1


def test_qualify_share_counts_completions() -> None:
    scenario = compute_scenarios(last_round(), "a1")

    assert scenario.completions == 9
    assert 0.6 < scenario.qualify_share < 1


# --- knockout ---------------------------------------------------------------------------------


def finished_groups() -> TournamentState:
    groups: dict[str | None, tuple[str, ...]] = {
        letter: tuple(f"{letter.lower()}{i}" for i in range(1, 5)) for letter in "ABCD"
    }
    results = [
        g(letter, h, a, 1, 0)
        for letter, members in groups.items()
        if letter is not None
        for h, a in itertools.combinations(members, 2)
    ]
    return make_state(groups, results, [], SIXTEEN)


def test_knockout_path_names_the_next_opponent_and_the_route() -> None:
    bracket = build_bracket(SIXTEEN.format, SIXTEEN.advancement)

    scenario = compute_scenarios(finished_groups(), "a1", bracket=bracket)

    assert scenario.status == "clinched"
    assert scenario.knockout is not None
    assert scenario.knockout.next_match == "QF1"
    assert scenario.knockout.opponent == "b2"
    assert scenario.knockout.route == ("QF1", "SF1", "F")


def test_losing_a_knockout_match_eliminates() -> None:
    bracket = build_bracket(SIXTEEN.format, SIXTEEN.advancement)
    lost = MatchResult("ko-qf1", None, "a1", "b2", FootballResult(0, 1))

    scenario = compute_scenarios(
        finished_groups(), "a1", bracket=bracket, knockout_results={"QF1": lost}
    )

    assert scenario.status == "eliminated"
    assert scenario.knockout is not None
    assert scenario.knockout.eliminated_in == "QF1"


# --- relevance --------------------------------------------------------------------------------


def test_rival_match_matters_more_than_another_group() -> None:
    items = match_relevance(last_round(), "a1")

    assert [i.match_id for i in items] == ["A:a2-a3", "B:b3-b4"]
    assert items[0].impact > 0
    assert items[1].impact == 0
    assert items[0].best_outcome in ("draw", "away")
    assert "a1-a4" not in {i.match_id.split(":")[1] for i in items}


# --- performance and properties ---------------------------------------------------------------


def test_six_teams_six_matches_left_is_fast() -> None:
    teams = tuple(f"a{i}" for i in range(1, 7))
    pairs = list(itertools.combinations(teams, 2))
    results = [g("A", h, a, (i * 7) % 3, (i * 5) % 2) for i, (h, a) in enumerate(pairs[:9])]
    fixtures = [fx("A", h, a) for h, a in pairs[9:]]
    choice = groups_then_knockout([6], per_group=2)
    state = make_state({"A": teams}, results, fixtures, choice)

    started = time.perf_counter()
    for team in teams:
        compute_scenarios(state, team)
    elapsed = time.perf_counter() - started

    assert len(fixtures) == 6
    assert elapsed < 1 * len(teams)


def _position(state: TournamentState, team: str) -> tuple[int, int]:
    """(best, worst) place the team can be given in the final table (a tie shares places)."""
    for group in compute_standings(state).groups:
        rows = group.rows
        for row in rows:
            if row.team == team:
                tied = [r for r in rows if r.position == row.position]
                return row.position, row.position + len(tied) - 1
    raise AssertionError(team)


PAIRS = list(itertools.combinations(("a1", "a2", "a3", "a4"), 2))
scores = st.tuples(st.integers(0, 4), st.integers(0, 4))


@settings(max_examples=80, deadline=None)
@given(
    played=st.lists(st.booleans(), min_size=6, max_size=6),
    played_scores=st.lists(scores, min_size=6, max_size=6),
    completion_scores=st.lists(st.lists(scores, min_size=6, max_size=6), min_size=5, max_size=5),
)
def test_property_clinched_and_eliminated_hold_in_every_completion(
    played: list[bool],
    played_scores: list[tuple[int, int]],
    completion_scores: list[list[tuple[int, int]]],
) -> None:
    results = [g("A", h, a, *played_scores[i]) for i, (h, a) in enumerate(PAIRS) if played[i]]
    fixtures = [fx("A", h, a) for i, (h, a) in enumerate(PAIRS) if not played[i]]
    state = make_state({"A": ("a1", "a2", "a3", "a4")}, results, fixtures)
    statuses = {team: compute_scenarios(state, team).status for team in ("a1", "a2", "a3", "a4")}

    for completion in completion_scores:
        finished = [g("A", h, a, *completion[i]) for i, (h, a) in enumerate(PAIRS) if not played[i]]
        final = make_state(state.groups, [*results, *finished], [])
        for team, status in statuses.items():
            best, worst = _position(final, team)
            if status == "clinched":
                assert worst <= 2
            if status == "eliminated":
                assert best > 2
