"""A small run of the load test (the full one: `uv run python -m app.scripts.loadtest`)."""

from collections.abc import Callable

from app.core.config import Settings
from app.scripts.loadtest import Plan, run


async def test_viewers_get_every_goal_quickly_while_matches_are_scored(
    database_url: str, make_settings: Callable[..., Settings]
) -> None:
    settings = make_settings(database_url=database_url)
    plan = Plan(
        viewers=60, live=6, cups=1, pitches=4, rounds=2, reads=60, concurrency=10, spread_ms=200
    )

    report = await run(plan, None, settings)

    assert report.viewers_connected == 60
    assert report.live_matches == 6 and report.pitches_live_in_main_cup == 4
    assert report.delivered >= 0.99
    assert report.event_ms["p95"] < 2000
    assert report.read_ms["n"] > 0 and report.personal_ms["n"] > 0
