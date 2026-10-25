from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.bracket import (
    Bracket,
    BracketResolution,
    SlotResolution,
    build_bracket,
    resolve_bracket,
)
from engine.model import Fixture, MatchResult, TeamRef, TournamentState
from engine.rules.config import AdvancementRule, RuleConfig
from engine.rules.format import FormatChoice, KnockoutSpec, groups_then_knockout, knockout_only
from engine.rules.presets import football_rules
from engine.sports.football import FootballResult

H2H_FIRST = "football_h2h_first"


def pairs(bracket: Bracket, round_: str | None = None) -> list[tuple[str, str, str]]:
    return [
        (m.code, m.home_source, m.away_source)
        for m in bracket.matches
        if round_ is None or m.round == round_
    ]


# --- building --------------------------------------------------------------------------------


def test_sixteen_teams_world_cup_style_quarter_finals() -> None:
    choice = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)

    bracket = build_bracket(choice.format, choice.advancement)

    assert pairs(bracket) == [
        ("QF1", "group:A:1", "group:B:2"),
        ("QF2", "group:C:1", "group:D:2"),
        ("QF3", "group:B:1", "group:A:2"),
        ("QF4", "group:D:1", "group:C:2"),
        ("SF1", "winner:QF1", "winner:QF2"),
        ("SF2", "winner:QF3", "winner:QF4"),
        ("3P", "loser:SF1", "loser:SF2"),
        ("F", "winner:SF1", "winner:SF2"),
    ]


def test_eight_teams_two_groups_semi_finals() -> None:
    choice = groups_then_knockout([4, 4], per_group=2)

    assert pairs(build_bracket(choice.format, choice.advancement), "semi_final") == [
        ("SF1", "group:A:1", "group:B:2"),
        ("SF2", "group:B:1", "group:A:2"),
    ]


def test_group_winners_only_pair_neighbouring_groups() -> None:
    choice = groups_then_knockout([3, 3, 3, 3], per_group=1)

    assert pairs(build_bracket(choice.format, choice.advancement), "semi_final") == [
        ("SF1", "group:A:1", "group:B:1"),
        ("SF2", "group:C:1", "group:D:1"),
    ]


def test_pure_knockout_uses_standard_seeding() -> None:
    choice = knockout_only(8)

    assert pairs(build_bracket(choice.format, choice.advancement), "quarter_final") == [
        ("QF1", "seed:1", "seed:8"),
        ("QF2", "seed:4", "seed:5"),
        ("QF3", "seed:2", "seed:7"),
        ("QF4", "seed:3", "seed:6"),
    ]


def test_single_group_top_four_to_semis() -> None:
    choice = FormatChoice(
        groups_then_knockout([6], per_group=2).format.model_copy(
            update={"knockout": KnockoutSpec(rounds=["semi_final", "final"])}
        ),
        AdvancementRule(per_group=4),
    )

    assert pairs(build_bracket(choice.format, choice.advancement), "semi_final") == [
        ("SF1", "group:A:1", "group:A:4"),
        ("SF2", "group:A:2", "group:A:3"),
    ]


def test_custom_pairs_are_used_as_given() -> None:
    choice = groups_then_knockout([4, 4], per_group=2)
    custom = choice.format.model_copy(
        update={
            "knockout": KnockoutSpec(
                rounds=["semi_final", "final"],
                crossover="custom",
                custom_pairs=[("group:A:1", "group:A:2"), ("group:B:1", "group:B:2")],
            )
        }
    )

    assert pairs(build_bracket(custom, choice.advancement), "semi_final") == [
        ("SF1", "group:A:1", "group:A:2"),
        ("SF2", "group:B:1", "group:B:2"),
    ]


def _group(source: str) -> str | None:
    parts = source.split(":")
    return parts[1] if parts[0] == "group" else None


def test_twenty_four_teams_with_best_thirds() -> None:
    choice = groups_then_knockout([4] * 6, per_group=2, best_of_rest=4)

    bracket = build_bracket(choice.format, choice.advancement)

    first = [m for m in bracket.matches if m.round == "round_of_16"]
    sources = [s for m in first for s in (m.home_source, m.away_source)]
    assert len(first) == 8
    assert Counter(sources) == Counter(
        [f"group:{g}:{p}" for g in "ABCDEF" for p in (1, 2)]
        + [f"best_rest:{k}" for k in (1, 2, 3, 4)]
    )
    for match in first:  # never two teams of the same group in round one
        home, away = _group(match.home_source), _group(match.away_source)
        assert home is None or home != away
    thirds_opponents = [m.home_source for m in first if m.away_source.startswith("best_rest")]
    assert all(s.endswith(":1") for s in thirds_opponents)  # thirds face group winners
    # Teams of the same group are in opposite halves of the bracket.
    for half in (first[:4], first[4:]):
        groups = [_group(s) for m in half for s in (m.home_source, m.away_source)]
        named = [grp for grp in groups if grp is not None]
        assert len(named) == len(set(named))


# --- resolving -------------------------------------------------------------------------------


def g(group: str, home: str, away: str, hg: int, ag: int) -> MatchResult:
    return MatchResult(f"{group}:{home}-{away}", group, home, away, FootballResult(hg, ag))


def finished_group(letter: str, third_margin: int = 1) -> list[MatchResult]:
    """Teams X1…X4 finish in that order; X3 beats X4 by `third_margin`."""
    teams = [f"{letter}{i}" for i in range(1, 5)]
    results = []
    for i, home in enumerate(teams):
        for away in teams[i + 1 :]:
            margin = third_margin if (home, away) == (teams[2], teams[3]) else 1
            results.append(g(letter, home, away, margin, 0))
    return results


def make_state(
    letters: str,
    results: Sequence[MatchResult],
    *,
    fixtures: Sequence[Fixture] = (),
    choice: FormatChoice,
    rules: RuleConfig | None = None,
) -> TournamentState:
    groups: dict[str | None, tuple[str, ...]] = {
        letter: tuple(f"{letter}{i}" for i in range(1, 5)) for letter in letters
    }
    teams = [t for members in groups.values() for t in members]
    return TournamentState(
        teams=tuple(TeamRef(t, t) for t in teams),
        groups=groups,
        results=tuple(results),
        fixtures=tuple(fixtures),
        rules=rules or football_rules(H2H_FIRST, choice),
        format=choice.format,
    )


def slot(resolution: BracketResolution, code: str, side: str = "home") -> SlotResolution:
    match = next(m for m in resolution.matches if m.code == code)
    resolved: SlotResolution = getattr(match, side)
    return resolved


SIXTEEN = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)


def test_finished_groups_fill_the_quarter_finals() -> None:
    results = [r for letter in "ABCD" for r in finished_group(letter)]
    state = make_state("ABCD", results, choice=SIXTEEN)

    resolution = resolve_bracket(build_bracket(SIXTEEN.format, SIXTEEN.advancement), state)

    assert slot(resolution, "QF1").team == "A1"
    assert slot(resolution, "QF1", "away").team == "B2"
    assert slot(resolution, "QF1").status == "resolved"
    assert slot(resolution, "SF1").status == "pending"
    assert set(slot(resolution, "SF1").could_be) == {"A1", "B2"}


def _remaining(
    results: Sequence[MatchResult], played: int
) -> tuple[list[MatchResult], list[Fixture]]:
    done, rest = list(results[:played]), results[played:]
    fixtures = [
        Fixture(r.match_id, r.group_id, r.home, r.away, starts_at="2026-06-13T10:00:00Z")
        for r in rest
    ]
    return done, fixtures


def test_unfinished_group_resolves_certain_places_early_and_lists_the_rest() -> None:
    group_a = finished_group("A")
    played, fixtures = _remaining(group_a, 3)  # A1 has won all three; A2-A4 still to play
    others = [r for letter in "BCD" for r in finished_group(letter)]
    state = make_state("ABCD", [*played, *others], fixtures=fixtures, choice=SIXTEEN)

    resolution = resolve_bracket(build_bracket(SIXTEEN.format, SIXTEEN.advancement), state)

    winner_a = slot(resolution, "QF1")
    assert (winner_a.team, winner_a.status) == ("A1", "resolved")  # 9 points, nobody can reach 9
    runner_up_a = slot(resolution, "QF3", "away")
    assert runner_up_a.status == "pending"
    assert runner_up_a.team is None
    assert set(runner_up_a.could_be) == {"A2", "A3", "A4"}
    assert slot(resolution, "QF1", "away").team == "B2"


def test_unbreakable_tie_blocks_the_slot_until_lots_are_drawn() -> None:
    choice = groups_then_knockout([4, 4], per_group=2)
    level = [
        g("A", h, a, 1, 1)
        for i, h in enumerate(["A1", "A2", "A3", "A4"])
        for a in ["A1", "A2", "A3", "A4"][i + 1 :]
    ]
    state = make_state("AB", [*level, *finished_group("B")], choice=choice)

    resolution = resolve_bracket(build_bracket(choice.format, choice.advancement), state)

    blocked = slot(resolution, "SF1")
    assert blocked.status == "blocked"
    assert blocked.blocked_reason == "draw_lots"
    assert set(blocked.could_be) == {"A1", "A2", "A3", "A4"}


def test_knockout_results_resolve_winners_and_losers() -> None:
    results = [r for letter in "ABCD" for r in finished_group(letter)]
    state = make_state("ABCD", results, choice=SIXTEEN)
    knockout = {
        "QF1": MatchResult("qf1", None, "A1", "B2", FootballResult(0, 1)),
        "QF2": MatchResult("qf2", None, "C1", "D2", FootballResult(2, 0)),
        "QF3": MatchResult("qf3", None, "B1", "A2", FootballResult(1, 1, "penalties", 5, 4)),
        "QF4": MatchResult("qf4", None, "D1", "C2", FootballResult(3, 2, "extra_time")),
        "SF1": MatchResult("sf1", None, "B2", "C1", FootballResult(1, 2)),
    }

    resolution = resolve_bracket(
        build_bracket(SIXTEEN.format, SIXTEEN.advancement), state, knockout_results=knockout
    )

    assert (slot(resolution, "SF1").team, slot(resolution, "SF1", "away").team) == ("B2", "C1")
    assert (slot(resolution, "SF2").team, slot(resolution, "SF2", "away").team) == ("B1", "D1")
    assert slot(resolution, "F").team == "C1"
    assert slot(resolution, "3P").team == "B2"
    assert set(slot(resolution, "F", "away").could_be) == {"B1", "D1"}


def test_best_thirds_never_face_their_own_group_winner() -> None:
    choice = groups_then_knockout([4] * 6, per_group=2, best_of_rest=4)
    margins = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "F": 1}  # thirds from A-D qualify
    results = [r for letter, m in margins.items() for r in finished_group(letter, m)]
    rules = football_rules(H2H_FIRST, choice)
    state = make_state("ABCDEF", results, choice=choice, rules=rules)

    resolution = resolve_bracket(build_bracket(choice.format, choice.advancement), state)

    first = [m for m in resolution.matches if m.round == "round_of_16"]
    thirds = {m.away.team for m in first if m.away.source.startswith("best_rest")}
    assert thirds == {"A3", "B3", "C3", "D3"}
    for match in first:
        assert match.home.team is not None and match.away.team is not None
        assert match.home.team[0] != match.away.team[0]


def test_pure_knockout_seeds_come_from_the_draw() -> None:
    choice = knockout_only(4)
    state = TournamentState(
        teams=tuple(TeamRef(t, t) for t in "wxyz"),
        groups={},
        results=(),
        fixtures=(),
        rules=football_rules(H2H_FIRST, choice),
        format=choice.format,
    )

    resolution = resolve_bracket(
        build_bracket(choice.format, choice.advancement),
        state,
        seeds={"seed:1": "w", "seed:2": "x", "seed:3": "y", "seed:4": "z"},
    )

    assert (slot(resolution, "SF1").team, slot(resolution, "SF1", "away").team) == ("w", "z")


# --- properties ------------------------------------------------------------------------------

TWO_GROUPS = groups_then_knockout([4, 4], per_group=2)
TEAMS = {letter: [f"{letter}{i}" for i in range(1, 5)] for letter in "AB"}
PAIRS = [
    (letter, h, a)
    for letter, members in TEAMS.items()
    for i, h in enumerate(members)
    for a in members[i + 1 :]
]
score = st.integers(min_value=0, max_value=3)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(st.tuples(score, score), min_size=len(PAIRS), max_size=len(PAIRS)),
    st.permutations(range(len(PAIRS))),
)
def test_resolved_slots_never_change_and_could_be_always_contains_the_outcome(
    goals: list[tuple[int, int]], play_order: list[int]
) -> None:
    results = [g(letter, h, a, *goals[i]) for i, (letter, h, a) in enumerate(PAIRS)]
    ordered = [results[i] for i in play_order]
    bracket = build_bracket(TWO_GROUPS.format, TWO_GROUPS.advancement)

    def resolve(played: int) -> BracketResolution:
        done, fixtures = _remaining(ordered, played)
        return resolve_bracket(
            bracket, make_state("AB", done, fixtures=fixtures, choice=TWO_GROUPS)
        )

    final = resolve(len(ordered))
    final_slots = _slots(final)
    for played in range(len(ordered) + 1):
        for source, current in _slots(resolve(played)).items():
            outcome = final_slots[source]
            if current.status == "resolved":
                assert outcome.team == current.team
            if outcome.status == "resolved":
                assert outcome.team in (current.could_be or (current.team,))


def _slots(resolution: BracketResolution) -> Mapping[str, Any]:
    return {
        s.source: s
        for m in resolution.matches
        for s in (m.home, m.away)
        if s.source.startswith("group:")
    }
