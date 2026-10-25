"""Editorial: corrected results republish the report, held stories go through the review
queue, readers report mistakes."""

import asyncio
import datetime as dt
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.config import Settings
from app.core.live import LiveHub, match_channel
from app.core.llm import FakeProvider, LLMGateway
from app.core.security import AccessClaims, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut
from app.modules.content import fake_writer
from app.modules.content import service as content
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
SECRET = "test-secret-not-for-real-use-0123456789abcdef"


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


async def finished_match(db: AsyncSession, clock: FrozenClock, cup: dict[str, Any]) -> MatchOut:
    """A group match won 2-1, with its read models computed."""
    tid = cup["tournament_id"]
    owner = Viewer(user_id=cup["owner"])
    await competitions.update_settings(db, tid, {"languages": ["fi", "en", "bn"]})
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    home, away = match.home_team_id, match.away_team_id
    await scoring.start(db, clock, owner, match.id)
    for n, (team, minute) in enumerate([(away, 10), (home, 30), (home, 38)], start=1):
        await scoring.post_event(
            db, clock, owner, match.id,
            EventIn(client_seq=n, type="goal", team_id=team, clock=f"{minute}:00"),
        )  # fmt: skip
    clock.set(KICK_OFF + dt.timedelta(minutes=40))
    await scoring.finish(db, clock, owner, match.id, 2, 1)
    await analysis.recalc_tournament(db, clock, tid)
    return match


async def _next_of(socket: asyncio.Queue[dict[str, Any]], kind: str) -> dict[str, Any]:
    while True:
        message = await socket.get()
        if message["type"] == kind and "story_corrected" in message["data"]:
            return message


async def test_correcting_a_goal_republishes_the_report_as_corrected(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    hub: LiveHub,
) -> None:
    clock.set(KICK_OFF)
    match = await finished_match(db, clock, published_cup)
    llm = gateway(fake_writer.responses())
    await content.write_story(db, clock, llm, "match", match.id, "report")
    socket = await hub.subscribe(match_channel(match.id))
    jobs.deferred.clear()

    clock.set(KICK_OFF + dt.timedelta(hours=2))
    owner = Viewer(user_id=published_cup["owner"])
    corrected = await scoring.undo(db, clock, owner, match.id, 3, 4, hub)  # the late winner
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    [job] = [j.args for j in jobs.deferred if j.name == "write_story"]
    stories = await content.write_story(
        db, clock, llm, "match", match.id, "report", correction=job["correction"], live=hub
    )

    assert corrected.live.home_goals == 1
    assert (await competitions.get_match(db, match.id)).result == {
        "home_goals": 1, "away_goals": 1, "decided_by": "regulation",
        "home_penalties": None, "away_penalties": None,
    }  # fmt: skip
    assert job["correction"] is True and len(stories) == 3
    assert all(s.corrected_at == clock.now() for s in stories)
    served = api.get(f"/api/v1/matches/{match.id}/stories?lang=en").json()
    assert served[0]["corrected_at"] and "1-1" in served[0]["body"]
    message = await asyncio.wait_for(_next_of(socket, "correction"), timeout=3)
    assert {s["language"] for s in message["data"]["story_corrected"]} == {"fi", "en", "bn"}


def wrong_score(task: str, prompt: str) -> dict[str, Any]:
    good = fake_writer.write(task, prompt)
    for text in good.values():
        text["sentences"].insert(0, {"text": "It finished 9-9 in the end.", "facts": ["f1"]})
    return good


def sign_in(
    api: TestClient, clock: FrozenClock, user_id: UUID, roles: frozenset[str]
) -> dict[str, str]:
    claims = AccessClaims(user_id, uuid4(), roles, clock.now() + dt.timedelta(minutes=10))
    api.cookies.set(ACCESS_COOKIE, encode_access_token(claims, SECRET))
    api.cookies.set(CSRF_COOKIE, "csrf-test-token")
    return {CSRF_HEADER: "csrf-test-token"}


async def test_an_editor_fixes_and_approves_a_held_story(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    clock.set(KICK_OFF)
    match = await finished_match(db, clock, published_cup)
    await content.write_story(
        db, clock, gateway({"report.v1": wrong_score}), "match", match.id, "report"
    )
    member, editor = await make_user(), await make_user()

    headers = sign_in(api, clock, member, frozenset())
    denied = api.get("/api/v1/review-queue")
    headers = sign_in(api, clock, editor, frozenset({"editor"}))
    queue = api.get("/api/v1/review-queue?reason=blocked_claim").json()
    taken = api.post("/api/v1/review-queue/take-next", headers=headers).json()
    story_id = taken["story"]["id"]
    english = next(e for e in queue if e["story"]["language"] == "en")
    item = api.get(f"/api/v1/review-queue/{english['story']['id']}").json()
    bad_text = item["story"]["body"]
    fixed = bad_text.replace("It finished 9-9 in the end. ", "")
    stale = api.patch(
        f"/api/v1/stories/{english['story']['id']}",
        json={"headline": item["story"]["headline"], "body": fixed},
        headers={**headers, "If-Match": '"999"'},
    )
    edited = api.patch(
        f"/api/v1/stories/{english['story']['id']}",
        json={"headline": item["story"]["headline"], "body": fixed},
        headers={**headers, "If-Match": f'"{item["story"]["version"]}"'},
    )
    check = api.post(f"/api/v1/stories/{english['story']['id']}/check", headers=headers).json()
    approved = api.post(f"/api/v1/stories/{english['story']['id']}/approve", headers=headers)
    served = api.get(f"/api/v1/matches/{match.id}/stories?lang=en").json()

    assert denied.status_code == 404
    assert len(queue) == 3 and all(e["story"]["review_reason"] == "blocked_claim" for e in queue)
    assert taken["claimed_by"] == str(editor) and story_id
    assert any(i["kind"] == "number" for i in item["story"]["check_result"]["issues"])
    assert stale.status_code == 409
    assert edited.status_code == 200 and edited.json()["story"]["versions"]
    assert check["passed"], check
    assert approved.status_code == 200 and approved.json()["status"] == "published"
    assert served[0]["ai_label"] == "Written by AI from match data, reviewed by an editor"


async def test_readers_report_mistakes_and_editors_resolve_them(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    clock.set(KICK_OFF)
    match = await finished_match(db, clock, published_cup)
    [story, *_] = await content.write_story(
        db, clock, gateway(fake_writer.responses()), "match", match.id, "report"
    )
    reader, editor = await make_user(), await make_user()

    headers = sign_in(api, clock, reader, frozenset())
    reported = api.post(
        f"/api/v1/stories/{story.id}/corrections",
        json={"text": "The winner was scored in minute 37."},
        headers=headers,
    )
    unknown = api.post(
        f"/api/v1/stories/{uuid4()}/corrections", json={"text": "Wrong."}, headers=headers
    )
    headers = sign_in(api, clock, editor, frozenset({"editor"}))
    listed = api.get("/api/v1/corrections").json()
    resolved = api.patch(
        f"/api/v1/corrections/{listed[0]['id']}",
        json={"status": "fixed", "note": "Minute corrected by the organiser."},
        headers=headers,
    )

    assert reported.status_code == 201
    assert unknown.status_code == 404
    assert [c["story_id"] for c in listed] == [str(story.id)]
    assert listed[0]["story_headline"] == story.headline
    assert listed[0]["story_status"] == "published"
    assert resolved.json()["status"] == "fixed"
    assert api.get("/api/v1/corrections").json() == []


async def test_editors_list_published_and_unpublished_stories(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    clock.set(KICK_OFF)
    match = await finished_match(db, clock, published_cup)
    [story, *_] = await content.write_story(
        db, clock, gateway(fake_writer.responses()), "match", match.id, "report"
    )
    member, editor = await make_user(), await make_user()

    sign_in(api, clock, member, frozenset())
    denied = api.get("/api/v1/editor/stories")
    headers = sign_in(api, clock, editor, frozenset({"editor"}))
    published = api.get("/api/v1/editor/stories").json()
    api.post(
        f"/api/v1/stories/{story.id}/unpublish",
        json={"reason": "Wrong team named."},
        headers=headers,
    )
    unpublished = api.get("/api/v1/editor/stories?status=unpublished").json()

    assert denied.status_code == 404
    assert str(story.id) in {s["id"] for s in published}
    assert (str(story.id), "Wrong team named.") in {
        (s["id"], s["removal_reason"]) for s in unpublished
    }
