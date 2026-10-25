import itertools
import time

from engine.analysis import analyse_match
from engine.bracket import build_bracket
from engine.comparison import compare_teams
from engine.model import EventLite, Fixture, MatchResult, TeamRef, TournamentState
from engine.ratings import RatingInfo
from engine.rules.format import groups_then_knockout
from engine.rules.presets import football_rules
from engine.simulation import simulate
from engine.sports.football import FootballResult

H, A = "home-fc", "away-fc"
NAMES = {H: "Home FC", A: "Away FC"}


def r(mid: str, home: str, away: str, hg: int, ag: int, when: str = "2026-06-12") -> MatchResult:
    return MatchResult(mid, "A", home, away, FootballResult(hg, ag), starts_at=when)


def goal(seq: int, team: str, minute: int) -> EventLite:
    return EventLite(seq=seq, type="goal", team=team, payload={"minute": minute})


def test_comparison_includes_previous_editions() -> None:
    results = [
        r("2025-sf", H, A, 2, 1, "2025-06-14"),
        r("2026-a1", H, "x", 0, 0),
        r("2026-a2", A, "y", 3, 0),
        r("2026-a3", A, H, 1, 1),
    ]

    c = compare_teams(results, H, A)

    assert [m.match_id for m in c.head_to_head] == ["2025-sf", "2026-a3"]
    assert c.head_to_head[0].winner == H
    assert c.b.clean_sheets == 1 and c.b.form == ("L", "W", "D")
    assert c.rating_gap == "no results to compare yet"


def test_comeback_late_winner_upset_table_and_qualification_facts() -> None:
    events = [goal(1, A, 10), goal(2, A, 22), goal(3, H, 30), goal(4, H, 33), goal(5, H, 38)]

    facts = analyse_match(
        H,
        A,
        events,
        FootballResult(3, 2),
        names=NAMES,
        match_minutes=40,
        win_chance={H: 0.25, A: 0.55},
        position_before={H: 3, A: 1},
        position_after={H: 2, A: 1},
        status_before={H: "alive", A: "alive"},
        status_after={H: "clinched", A: "alive"},
    )

    kinds = {f.kind: f for f in facts}
    assert kinds["result"].claim == "Home FC 3-2 Away FC"
    assert kinds["comeback"].value == 2
    assert kinds["late_winner"].value == 38
    assert kinds["upset"].claim.startswith("Home FC won as underdogs")
    assert kinds["table"].claim == "Home FC moved from 3 to 2 in the group"
    assert kinds["qualified"].team == H


def test_an_early_winner_is_not_late_and_a_favourite_is_no_upset() -> None:
    facts = analyse_match(
        H,
        A,
        [goal(1, H, 5)],
        FootballResult(1, 0),
        names=NAMES,
        match_minutes=40,
        win_chance={H: 0.6},
    )

    assert {f.kind for f in facts} == {"result"}


def cup_state(played: int) -> TournamentState:
    choice = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)
    groups: dict[str | None, tuple[str, ...]] = {
        g: tuple(f"{g.lower()}{i}" for i in range(1, 5)) for g in "ABCD"
    }
    results, fixtures = [], []
    for g, members in groups.items():
        for n, (h, a) in enumerate(itertools.combinations(members, 2)):
            if n < played:
                results.append(MatchResult(f"{g}{n}", g, h, a, FootballResult(1, 0)))
            else:
                fixtures.append(Fixture(f"{g}{n}", g, h, a, starts_at="2026-06-13"))
    teams = tuple(TeamRef(t, t) for ts in groups.values() for t in ts)
    return TournamentState(
        teams,
        groups,
        tuple(results),
        tuple(fixtures),
        football_rules("football_h2h_first", choice),
        choice.format,
    )


def test_simulation_is_deterministic_and_probabilities_add_up() -> None:
    state = cup_state(played=2)
    choice = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)
    bracket = build_bracket(choice.format, choice.advancement)
    ratings = {"a1": RatingInfo("a1", 1700, 10)}

    one = simulate(state, ratings, bracket=bracket, runs=2000, seed=b"s")
    two = simulate(state, ratings, bracket=bracket, runs=2000, seed=b"s")

    assert one == two
    assert abs(sum(c.win for c in one.values()) - 1) < 1e-9
    assert abs(sum(c.qualify for c in one.values()) - 8) < 1e-9
    assert one["a1"].win_group > one["a4"].win_group
    assert abs(sum(c.reach.get("quarter_final", 0) for c in one.values()) - 8) < 1e-9


def test_ten_thousand_runs_of_thirty_fixtures_under_three_seconds() -> None:
    choice = groups_then_knockout([5, 5, 5], per_group=2, best_of_rest=2, third_place_match=True)
    groups: dict[str | None, tuple[str, ...]] = {
        g: tuple(f"{g.lower()}{i}" for i in range(1, 6)) for g in "ABC"
    }
    fixtures = tuple(
        Fixture(f"{g}{n}", g, h, a, starts_at="2026-06-13")
        for g, members in groups.items()
        for n, (h, a) in enumerate(itertools.combinations(members, 2))
    )
    teams = tuple(TeamRef(t, t) for ts in groups.values() for t in ts)
    state = TournamentState(
        teams, groups, (), fixtures, football_rules("football_h2h_first", choice), choice.format
    )
    bracket = build_bracket(choice.format, choice.advancement)

    started = time.perf_counter()
    simulate(state, {}, bracket=bracket, runs=10_000)
    elapsed = time.perf_counter() - started

    assert len(fixtures) == 30
    assert elapsed < 3, elapsed
