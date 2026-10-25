"""Event lists per sport for the scorer console (S2): GET /sports/{sport}/event-types.

The console renders its pad only from this list, so adding a sport needs no front-end change.
"""

from __future__ import annotations

from .models import EventType, SportEvents

E = EventType


def _start_controls(first: str) -> list[EventType]:
    return [
        E(id="start", label=f"Start {first}", icon="▶", group="control", team=False),
        E(id="period_end", label="End period", icon="⏸", group="control", team=False),
        E(id="period_start", label="Start next period", icon="▶", group="control", team=False),
    ]


def _goal_sport(sport: str, penalty: list[EventType], periods: list[str], minutes: int) -> SportEvents:
    return SportEvents(
        sport=sport, pad="split", clock=True, period_minutes=minutes, periods=periods, score_label="Goals",
        event_types=[
            E(id="goal", label="Goal", icon="⚽" if sport == "football" else "🥅", group="score", points=1, player="optional",
              player_prompt="Who scored?", follow_up="assist"),
            E(id="assist", label="Assist", icon="🅰", group="play", player="required", player_prompt="Assist by?"),
            *penalty,
            E(id="substitution", label="Substitution", icon="🔁", group="play", player="optional", player_prompt="Player coming on?"),
            *_start_controls(periods[0]),
        ],
    )


SPORTS: dict[str, SportEvents] = {
    "football": _goal_sport("football", [
        E(id="yellow_card", label="Yellow card", icon="🟨", group="discipline", player="required", player_prompt="Who was booked?"),
        E(id="red_card", label="Red card", icon="🟥", group="discipline", player="required", player_prompt="Who was sent off?"),
        E(id="penalty_goal", label="Penalty scored", icon="🎯", group="score", points=1, player="optional", player_prompt="Penalty taker?"),
        E(id="penalty_miss", label="Penalty missed", icon="✖", group="play", player="optional", player_prompt="Penalty taker?"),
    ], ["1st half", "2nd half"], 45),
    "floorball": _goal_sport("floorball", [
        E(id="penalty_2", label="2-min penalty", icon="⏱", group="discipline", player="required", player_prompt="Penalised player?"),
        E(id="penalty_shot_goal", label="Penalty shot goal", icon="🎯", group="score", points=1, player="optional", player_prompt="Shooter?"),
    ], ["1st period", "2nd period", "3rd period"], 20),
    "ice-hockey": _goal_sport("ice-hockey", [
        E(id="penalty_2", label="2-min penalty", icon="⏱", group="discipline", player="required", player_prompt="Penalised player?"),
        E(id="penalty_shot_goal", label="Penalty shot goal", icon="🎯", group="score", points=1, player="optional", player_prompt="Shooter?"),
    ], ["1st period", "2nd period", "3rd period"], 20),
    "basketball": SportEvents(
        sport="basketball", pad="split", clock=True, period_minutes=10, score_label="Points",
        periods=["1st quarter", "2nd quarter", "3rd quarter", "4th quarter"],
        event_types=[
            E(id="pt1", label="Free throw", icon="①", group="score", points=1, player="optional", player_prompt="Shooter?"),
            E(id="pt2", label="2 points", icon="②", group="score", points=2, player="optional", player_prompt="Shooter?"),
            E(id="pt3", label="3 points", icon="③", group="score", points=3, player="optional", player_prompt="Shooter?"),
            E(id="foul", label="Foul", icon="✋", group="discipline", player="optional", player_prompt="Who fouled?"),
            *_start_controls("1st quarter"),
        ],
    ),
    "volleyball": SportEvents(
        sport="volleyball", pad="split", clock=False, score_label="Points",
        periods=["Set 1", "Set 2", "Set 3", "Set 4", "Set 5"],
        event_types=[
            E(id="point", label="Point", icon="🏐", group="score", points=1),
            E(id="ace", label="Ace", icon="⚡", group="score", points=1, player="optional", player_prompt="Server?"),
            E(id="timeout", label="Timeout", icon="⏸", group="play"),
            *_start_controls("Set 1"),
        ],
    ),
    "cricket": SportEvents(
        sport="cricket", pad="batting", clock=False, score_label="Runs", periods=["1st innings", "2nd innings"],
        event_types=[
            *[E(id=f"run_{n}", label=f"{n}", icon=["•", "1", "2", "3", "4", "5", "6"][n], group="score", points=n, ball=True,
                feed=n in (4, 6)) for n in range(7)],
            E(id="wide", label="Wide", icon="↔", group="score", points=1, feed=False),
            E(id="no_ball", label="No-ball", icon="⊘", group="score", points=1, feed=False),
            E(id="bye", label="Bye", icon="B", group="score", points=1, ball=True, feed=False),
            E(id="leg_bye", label="Leg bye", icon="LB", group="score", points=1, ball=True, feed=False),
            E(id="wicket", label="Wicket", icon="☝", group="score", ball=True, wicket=True, player="optional",
              player_prompt="Batter out?"),
            *_start_controls("1st innings"),
        ],
    ),
}


def for_sport(sport: str) -> SportEvents | None:
    return SPORTS.get(sport)
