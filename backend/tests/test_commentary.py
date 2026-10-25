"""Live commentary from scorer events: cadence, template fallback, audience priority."""

import asyncio
import datetime as dt
import os
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.config import Settings
from app.core.live import LiveHub, match_channel
from app.core.llm import FakeProvider, LLMGateway, ProviderError
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut
from app.modules.content import commentary, fake_writer
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"])
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def hub(redis: Redis) -> AsyncIterator[LiveHub]:
    live = LiveHub(redis)
    yield live
    await live.close()


@pytest.fixture
def gateway(
    make_settings: Callable[..., Settings], redis: Redis, clock: FrozenClock
) -> Callable[[dict[str, Any]], LLMGateway]:
    def build(responses: dict[str, Any]) -> LLMGateway:
        return LLMGateway(FakeProvider(responses=responses), make_settings(), redis, clock)

    return build


async def kick_off(
    db: AsyncSession, clock: FrozenClock, cup: dict[str, Any], count: int = 1
) -> list[MatchOut]:
    tid = cup["tournament_id"]
    await competitions.update_settings(db, tid, {"languages": ["fi", "en", "bn"]})
    await analysis.recalc_tournament(db, clock, tid)
    matches = [m for m in await competitions.list_matches(db, tid) if m.stage == "group"]
    for m in matches[:count]:
        await scoring.start(db, clock, Viewer(user_id=cup["owner"]), m.id)
    return matches[:count]


async def goal(
    db: AsyncSession, clock: FrozenClock, cup: dict[str, Any], match: MatchOut, n: int
) -> None:
    team = match.home_team_id if n % 2 else match.away_team_id
    minute = (clock.now() - KICK_OFF).seconds // 60
    await scoring.post_event(
        db, clock, Viewer(user_id=cup["owner"]), match.id,
        EventIn(client_seq=n, type="goal", team_id=team, clock=f"{minute}:00"),
    )  # fmt: skip


class Worker:
    """Runs deferred `write_commentary` jobs when they are due, like the worker would."""

    def __init__(self, db: AsyncSession, clock: FrozenClock, llm: LLMGateway, live: LiveHub):
        self.db, self.clock, self.llm, self.live = db, clock, llm, live
        self.seen = len(jobs.deferred)
        self.pending: list[tuple[dt.datetime, dict[str, Any]]] = []

    async def run_due(self) -> None:
        for job in jobs.deferred[self.seen :]:
            if job.name == "write_commentary":
                self.pending.append((job.run_at or self.clock.now(), job.args))
        self.seen = len(jobs.deferred)
        due = [p for p in self.pending if p[0] <= self.clock.now()]
        self.pending = [p for p in self.pending if p[0] > self.clock.now()]
        for _, args in sorted(due, key=lambda p: p[0]):
            await commentary.write_commentary(
                self.db, self.clock, self.llm, self.live, UUID(str(args["match_id"])),
                int(args["seq"]), str(args["moments"]).split(","),
            )  # fmt: skip
            await self.run_due()  # a job may defer itself to the end of the window


async def test_five_goals_in_two_minutes_give_at_most_three_lines(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    hub: LiveHub,
) -> None:
    clock.set(KICK_OFF)
    [match] = await kick_off(db, clock, published_cup)
    worker = Worker(db, clock, gateway(fake_writer.responses()), hub)
    start = KICK_OFF + dt.timedelta(minutes=10)
    for second in range(0, 181, 15):
        clock.set(start + dt.timedelta(seconds=second))
        if second in (0, 30, 60, 90, 120):
            await goal(db, clock, published_cup, match, second // 30 + 1)
        await worker.run_due()

    lines = await commentary.match_commentary(db, Viewer(), match.id)
    in_window = [c for c in lines if c.created_at <= start + dt.timedelta(minutes=2)]
    assert 2 <= len(in_window) <= 3
    assert max(c.seq for c in lines) == 5  # the last goal is covered after the window
    assert all(c.author_type == "ai" and c.ai_labels for c in lines)
    assert {i.language for i in lines[0].items} == {"fi", "en", "bn"}


async def test_an_llm_timeout_gives_a_template_line(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    hub: LiveHub,
) -> None:
    clock.set(KICK_OFF + dt.timedelta(minutes=5))
    [match] = await kick_off(db, clock, published_cup)
    timeout = ProviderError("timed out after 8 s", retryable=True)
    worker = Worker(db, clock, gateway({"commentary.v1": timeout}), hub)
    socket = await hub.subscribe(match_channel(match.id))

    await goal(db, clock, published_cup, match, 1)
    await worker.run_due()

    [line] = await commentary.match_commentary(db, Viewer(), match.id)
    texts = {i.language: i.text for i in line.items}
    assert line.author_type == "template" and line.ai_labels is None
    assert texts["en"].startswith("GOAL for") and "1-0" in texts["en"]
    assert texts["bn"].startswith("গোল!") and "১-০" in texts["bn"]
    message = await asyncio.wait_for(_next_of(socket, "commentary"), timeout=3)
    assert message["data"]["items"]


async def _next_of(socket: asyncio.Queue[dict[str, Any]], kind: str) -> dict[str, Any]:
    while True:
        message = await socket.get()
        if message["type"] == kind:
            return message


async def test_ai_lines_go_to_the_matches_with_the_largest_audience(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    hub: LiveHub,
) -> None:
    clock.set(KICK_OFF + dt.timedelta(minutes=5))
    matches = await kick_off(db, clock, published_cup, count=commentary.AI_SLOTS + 1)
    quiet = matches[-1]
    for n, m in enumerate(matches[:-1]):
        await hub.add_viewer(m.id, 50 + n)
    await hub.add_viewer(quiet.id, 1)
    worker = Worker(db, clock, gateway(fake_writer.responses()), hub)

    for m in matches:
        await goal(db, clock, published_cup, m, 1)
    await worker.run_due()

    authors = {
        m.id: (await commentary.match_commentary(db, Viewer(), m.id))[0].author_type
        for m in matches
    }
    assert authors[quiet.id] == "template"
    assert all(authors[m.id] == "ai" for m in matches[:-1])


async def test_commentary_follows_the_live_access_policy(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    hub: LiveHub,
) -> None:
    clock.set(KICK_OFF + dt.timedelta(minutes=5))
    [match] = await kick_off(db, clock, published_cup)
    worker = Worker(db, clock, gateway(fake_writer.responses()), hub)
    await goal(db, clock, published_cup, match, 1)
    await worker.run_due()
    url = f"/api/v1/matches/{match.id}/commentary"

    public = api.get(url)
    await competitions.update_settings(
        db, published_cup["tournament_id"], {"live_access": "members"}
    )
    gated = api.get(url)

    assert public.status_code == 200 and public.json()[0]["items"]
    assert gated.status_code == 403
