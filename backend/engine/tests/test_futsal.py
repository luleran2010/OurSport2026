"""Futsal: football's results and tables, plus accumulated fouls, timeouts and the
2 x 20 minute game (docs/04-engine.md, Sport modules)."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from engine.model import EventLite, MatchResult, TeamRef, TournamentState
from engine.rules.format import groups_then_knockout
from engine.rules.presets import futsal_match_rules, futsal_rules, sport_rules
from engine.rules.validate import validate_rule_config
from engine.sports.football import FootballResult
from engine.sports.futsal import FUTSAL, InvalidEvent
from engine.sports.registry import get_sport
from engine.standings import compute_standings

H, A = "home-fc", "away-fc"
CHOICE = groups_then_knockout([4], per_group=2, third_place_match=False)
RULES = futsal_rules("futsal_h2h_first", CHOICE)
KNOCKOUT = futsal_rules("futsal_h2h_first", CHOICE, match=futsal_match_rules(extra_time=True))


def ev(seq: int, type_: str, team: str | None = H, **payload: Any) -> EventLite:
    return EventLite(seq=seq, type=type_, team=team, payload=payload)


def start(seq: int, period: int) -> EventLite:
    return ev(seq, "period_start", None, period=period)


def end(seq: int, period: int) -> EventLite:
    return ev(seq, "period_end", None, period=period)


def test_futsal_is_registered_with_its_own_rules() -> None:
    assert get_sport("futsal") is FUTSAL
    assert RULES.sport == "futsal" and validate_rule_config(RULES) == []
    assert RULES.match["period_minutes"] == 20 and RULES.match["foul_limit"] == 5
    assert sport_rules("futsal", "futsal_gd_first", CHOICE).sport == "futsal"
    assert "foul" in FUTSAL.event_types and "timeout" in FUTSAL.event_types


def test_match_length_counts_a_stopped_clock() -> None:
    assert FUTSAL.match_duration_minutes(futsal_match_rules()) == 50  # 2 x 20 + 10
    assert FUTSAL.match_duration_minutes(futsal_match_rules(stopped_clock=True)) == 70


def test_the_sixth_accumulated_foul_is_a_moment_and_halves_reset_the_count() -> None:
    events = [start(1, 1), *(ev(n, "foul") for n in range(2, 7))]
    before = FUTSAL.replay(H, A, events, RULES)
    sixth = ev(7, "foul")
    after = FUTSAL.apply_event(before, sixth, RULES)

    assert before.home_fouls == 5
    assert "sixth_foul" not in FUTSAL.detect_moments(
        FUTSAL.replay(H, A, events[:-1], RULES), before, events[-1], RULES
    )
    assert FUTSAL.detect_moments(before, after, sixth, RULES) == ["sixth_foul"]
    second_half = FUTSAL.replay(H, A, [*events, sixth, end(8, 1), start(9, 2)], RULES)
    assert (second_half.home_fouls, second_half.away_fouls) == (0, 0)


def test_fouls_of_the_second_half_carry_into_extra_time() -> None:
    events = [
        start(1, 1),
        end(2, 1),
        start(3, 2),
        ev(4, "foul"),
        ev(5, "foul"),
        end(6, 2),
        start(7, 3),
    ]
    state = FUTSAL.replay(H, A, events, KNOCKOUT, knockout=True)

    assert state.period == 3 and state.home_fouls == 2


def test_one_timeout_per_team_per_half_and_none_in_extra_time() -> None:
    first = FUTSAL.replay(H, A, [start(1, 1), ev(2, "timeout")], RULES)
    FUTSAL.validate_event(first, ev(3, "timeout", A), RULES)
    with pytest.raises(InvalidEvent) as used:
        FUTSAL.validate_event(first, ev(3, "timeout"), RULES)
    second = FUTSAL.replay(H, A, [start(1, 1), ev(2, "timeout"), end(3, 1), start(4, 2)], RULES)
    FUTSAL.validate_event(second, ev(5, "timeout"), RULES)
    extra = FUTSAL.replay(
        H,
        A,
        [start(1, 1), end(2, 1), start(3, 2), end(4, 2), start(5, 3)],
        KNOCKOUT,
        knockout=True,
    )
    with pytest.raises(InvalidEvent) as late:
        FUTSAL.validate_event(extra, ev(6, "timeout"), KNOCKOUT)

    assert used.value.code == "timeout_used"
    assert late.value.code == "no_timeout_in_extra_time"
    assert "timeout" in FUTSAL.detect_moments(first, first, ev(3, "timeout", A))


def test_a_level_knockout_goes_to_extra_time_then_penalties() -> None:
    goals = [start(1, 1), ev(2, "goal"), end(3, 1), start(4, 2), ev(5, "goal", A), end(6, 2)]
    level = FUTSAL.replay(H, A, goals, KNOCKOUT, knockout=True)
    kicks = [start(7, 3), end(8, 3), start(9, 4), end(10, 4)]
    kicks += [ev(11, "shootout_kick", H, scored=True), ev(12, "shootout_kick", A, scored=False)]
    decided = FUTSAL.replay(H, A, goals + kicks, KNOCKOUT, knockout=True)
    result = FUTSAL.result_of(decided, KNOCKOUT)

    assert not level.finished
    assert result == FootballResult(1, 1, "penalties", 1, 0)
    assert FUTSAL.knockout_winner(MatchResult("ko", None, H, A, result)) == H


def test_golden_futsal_group_table_head_to_head_first() -> None:
    teams = ("a", "b", "c", "d")
    games = [
        ("a", "b", 2, 1),
        ("c", "d", 3, 3),
        ("a", "c", 1, 4),
        ("b", "d", 5, 0),
        ("a", "d", 2, 0),
        ("b", "c", 2, 2),
    ]
    state = TournamentState(
        tuple(TeamRef(t, t) for t in teams),
        {"A": teams},
        tuple(
            MatchResult(f"m{i}", "A", h, a, FootballResult(hg, ag))
            for i, (h, a, hg, ag) in enumerate(games)
        ),
        (),
        RULES,
        CHOICE.format,
    )

    rows = compute_standings(state).groups[0].rows

    # a 6 (W L W), c 5 (D W D), b 4 (L W D), d 1
    assert [r.team for r in rows] == ["a", "c", "b", "d"]
    assert [r.stats.points for r in rows] == [6, 5, 4, 1]


@given(st.lists(st.sampled_from([H, A]), max_size=14))
def test_foul_counts_match_the_fouls_of_the_half(fouls: list[str]) -> None:
    events = [start(1, 1), *(ev(n + 2, "foul", team) for n, team in enumerate(fouls))]
    state = FUTSAL.replay(H, A, events, RULES)
    moments: list[tuple[str | None, str]] = []
    for i in range(1, len(events)):
        before = FUTSAL.replay(H, A, events[:i], RULES)
        after = FUTSAL.apply_event(before, events[i], RULES)
        found = FUTSAL.detect_moments(before, after, events[i], RULES)
        moments.extend((events[i].team, m) for m in found)

    assert (state.home_fouls, state.away_fouls) == (fouls.count(H), fouls.count(A))
    for team in (H, A):
        expected = 1 if fouls.count(team) > RULES.match["foul_limit"] else 0
        assert moments.count((team, "sixth_foul")) == expected
