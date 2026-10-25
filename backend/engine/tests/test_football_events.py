from dataclasses import replace
from typing import Any

import pytest

from engine.model import EventLite, LiveStateLite
from engine.sports.football import FOOTBALL, InvalidEvent
from engine.tests.conftest import make_rules

HOME, AWAY = "home-fc", "away-fc"
RULES = make_rules()  # 2 periods, no extra time

LIVE = LiveStateLite(home=HOME, away=AWAY, home_goals=0, away_goals=0, period=1)


def event(type_: str, team: str | None = HOME, seq: int = 10, **payload: Any) -> EventLite:
    player = payload.pop("player", None)
    return EventLite(seq=seq, type=type_, team=team, player=player, payload=payload)


def rejected(state: LiveStateLite, ev: EventLite, **kwargs: Any) -> str:
    with pytest.raises(InvalidEvent) as caught:
        FOOTBALL.validate_event(state, ev, RULES, **kwargs)
    return caught.value.code


def test_normal_goal_is_accepted() -> None:
    FOOTBALL.validate_event(LIVE, event("goal", kind="header", player="p9"), RULES)


def test_goal_for_a_team_not_in_the_match_is_rejected() -> None:
    assert rejected(LIVE, event("goal", team="visitors-from-elsewhere")) == "team_not_in_match"


def test_unknown_event_type_is_rejected() -> None:
    assert rejected(LIVE, event("bicycle_kick")) == "invalid_event_type"


def test_unknown_goal_kind_is_rejected() -> None:
    assert rejected(LIVE, event("goal", kind="scorpion")) == "invalid_payload"


def test_events_after_full_time_are_rejected_unless_correcting() -> None:
    finished = replace(LIVE, finished=True)

    assert rejected(finished, event("goal")) == "event_after_full_time"
    FOOTBALL.validate_event(finished, event("goal"), RULES, allow_after_full_time=True)


def test_second_red_for_the_same_player_is_rejected() -> None:
    sent_off = replace(LIVE, sent_off=frozenset({"p4"}))

    assert rejected(sent_off, event("red_card", player="p4")) == "player_already_sent_off"
    assert rejected(sent_off, event("second_yellow", player="p4")) == "player_already_sent_off"
    assert rejected(sent_off, event("goal", player="p4")) == "player_already_sent_off"
    FOOTBALL.validate_event(sent_off, event("red_card", player="p5"), RULES)


def test_shootout_kicks_only_in_knockout() -> None:
    assert rejected(LIVE, event("shootout_kick", scored=True)) == "shootout_not_allowed"
    FOOTBALL.validate_event(
        replace(LIVE, knockout=True), event("shootout_kick", scored=True), RULES
    )


def test_shootout_kick_needs_a_result() -> None:
    knockout = replace(LIVE, knockout=True)

    assert rejected(knockout, event("shootout_kick")) == "invalid_payload"


def test_period_must_exist_under_the_rules() -> None:
    FOOTBALL.validate_event(LIVE, event("period_start", team=None, period=2), RULES)

    assert rejected(LIVE, event("period_start", team=None, period=3)) == "invalid_payload"


def test_extra_time_periods_exist_when_configured() -> None:
    with_extra_time = make_rules(match={"periods": 2, "period_minutes": 20, "extra_time": True})

    FOOTBALL.validate_event(LIVE, event("period_start", team=None, period=4), with_extra_time)


def test_undo_must_point_at_an_earlier_event() -> None:
    FOOTBALL.validate_event(LIVE, event("undo", team=None, seq=10, undoes_seq=9), RULES)

    assert rejected(LIVE, event("undo", team=None, seq=10, undoes_seq=10)) == "invalid_undo"
    assert rejected(LIVE, event("undo", team=None, seq=10)) == "invalid_undo"


def test_card_needs_a_team() -> None:
    assert rejected(LIVE, event("yellow_card", team=None)) == "team_not_in_match"


def test_own_goal_is_credited_to_the_other_team() -> None:
    own_goal = event("goal", team=HOME, kind="own_goal", player="p2")

    assert FOOTBALL.credited_team(LIVE, own_goal) == AWAY
    assert FOOTBALL.credited_team(LIVE, event("goal", team=HOME)) == HOME


# --- replay and moments -----------------------------------------------------------------------


def ev(seq: int, type_: str, team: str | None = HOME, **payload: Any) -> EventLite:
    return event(type_, team, seq, **payload)


def test_replay_skips_undone_events_and_ends_at_full_time() -> None:
    events = [
        ev(1, "period_start", None, period=1),
        ev(2, "goal"),
        ev(3, "goal", AWAY),
        ev(4, "undo", None, undoes_seq=3),
        ev(5, "period_end", None, period=1),
        ev(6, "period_start", None, period=2),
        ev(7, "goal", AWAY, kind="own_goal"),
        ev(8, "period_end", None, period=2),
    ]

    state = FOOTBALL.replay(HOME, AWAY, events, RULES)

    assert (state.home_goals, state.away_goals, state.finished) == (2, 0, True)
    assert FOOTBALL.result_of(state, RULES).decided_by == "regulation"


def test_level_knockout_match_goes_to_a_shootout() -> None:
    events = [
        ev(1, "period_start", None, period=1),
        ev(2, "period_end", None, period=2),
        ev(3, "shootout_kick", scored=True),
        ev(4, "shootout_kick", AWAY, scored=False),
    ]

    state = FOOTBALL.replay(HOME, AWAY, events, RULES, knockout=True)
    result = FOOTBALL.result_of(state, RULES)

    assert not state.finished
    assert (result.decided_by, result.home_penalties, result.away_penalties) == ("penalties", 1, 0)


def test_moments() -> None:
    start = LiveStateLite(HOME, AWAY, 0, 1, 1)
    level = replace(start, home_goals=1)
    ahead = replace(start, home_goals=2)

    assert FOOTBALL.detect_moments(start, level, ev(5, "goal")) == ["goal", "equaliser"]
    assert FOOTBALL.detect_moments(level, ahead, ev(6, "goal", kind="penalty")) == [
        "penalty_scored"
    ]
    behind = LiveStateLite(HOME, AWAY, 1, 2, 2)
    swapped = LiveStateLite(HOME, AWAY, 3, 2, 2)
    assert "lead_change" in FOOTBALL.detect_moments(behind, swapped, ev(7, "goal"))
    assert FOOTBALL.detect_moments(start, start, ev(8, "red_card", player="p1")) == ["red_card"]
    half = FOOTBALL.apply_event(start, ev(9, "period_end", None, period=1), RULES)
    assert FOOTBALL.detect_moments(start, half, ev(9, "period_end", None, period=1)) == [
        "half_time"
    ]
