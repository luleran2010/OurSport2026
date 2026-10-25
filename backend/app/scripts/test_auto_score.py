from typing import Any

import pytest

from app.scripts.auto_score import (
    client_from_scorer_url,
    clock_seconds,
    event_button,
    format_clock,
    post_period_event,
    select_match,
)


def test_scorer_url_requires_loopback_and_extracts_pass() -> None:
    client = client_from_scorer_url("http://localhost:5173/score?pass=demo-token")

    assert client.base_url == "http://localhost:5173"
    assert client.token == "demo-token"

    with pytest.raises(ValueError, match="loopback"):
        client_from_scorer_url("https://example.test/score?pass=demo-token")


def test_match_selection_filters_out_finished_and_results_only() -> None:
    matches: list[dict[str, Any]] = [
        {
            "match_id": "live-match",
            "status": "live",
            "data_level": "events",
            "home_team_id": "home",
            "away_team_id": "away",
        },
        {
            "match_id": "finished-match",
            "status": "finished",
            "data_level": "events",
            "home_team_id": "home",
            "away_team_id": "away",
        },
        {
            "match_id": "result-only-match",
            "status": "scheduled",
            "data_level": "results",
            "home_team_id": "home",
            "away_team_id": "away",
        },
    ]

    assert select_match(matches, None)["match_id"] == "live-match"


def test_event_selection_uses_supported_non_control_buttons() -> None:
    pad = {
        "sport": "football",
        "buttons": [
            {"id": "period_start", "group": "control", "knockout_only": False},
            {"id": "timeout", "group": "control", "knockout_only": False},
            {"id": "goal", "group": "score", "knockout_only": False},
            {"id": "shootout_scored", "group": "score", "knockout_only": True},
        ],
    }

    assert event_button(pad, {"stage": "group"})["id"] == "goal"


def test_match_clock_formats_and_resumes_from_previous_event() -> None:
    assert format_clock(40) == "0:40"
    assert format_clock(80) == "1:20"
    assert clock_seconds("1:20") == 80
    assert clock_seconds(None) == 0


def test_period_boundary_posts_period_and_match_clock() -> None:
    class Client:
        def request(self, path: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
            assert path == "/matches/demo-match/events"
            assert method == "POST"
            assert body == {
                "client_seq": 8,
                "type": "period_end",
                "payload": {"period": 1},
                "clock": "40:00",
            }
            return {"seq": 12}

    assert post_period_event(
        Client(), "demo-match", 8, "period_end", 1, "40:00"
    ) == {"seq": 12}
