"""Stories, recaps and announcements: written from facts in every language, checked,
published with the AI label, held for review when the checker keeps failing."""

import datetime as dt
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.config import Settings
from app.core.llm import FakeProvider, LLMGateway
from app.core.time import FrozenClock
from app.core.viewer import CSRF_HEADER, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut
from app.modules.content import fake_writer, team_backgrounds
from app.modules.content import service as content
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
LANGUAGES = ["fi", "en", "bn"]


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"])
    await client.flushdb()  # no cached LLM answers between tests
    yield client
    await client.aclose()


@pytest.fixture
def gateway(
    make_settings: Callable[..., Settings], redis: Redis, clock: FrozenClock
) -> Callable[[dict[str, Any]], LLMGateway]:
    def build(responses: dict[str, Any]) -> LLMGateway:
        return LLMGateway(FakeProvider(responses=responses), make_settings(), redis, clock)

    return build


async def play_and_finish(db: AsyncSession, clock: FrozenClock, cup: dict[str, Any]) -> MatchOut:
    """A group match with a late comeback, finished at 07:40."""
    tid = cup["tournament_id"]
    owner = Viewer(user_id=cup["owner"])
    await competitions.update_settings(db, tid, {"languages": LANGUAGES})
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
    return match


def deferred(name: str) -> list[dict[str, Any]]:
    return [j.args for j in jobs.deferred if j.name == name]


def report_with_fictional_flavor(task: str, prompt: str) -> dict[str, Any]:
    _, inputs = fake_writer._inputs(prompt)
    assert inputs["fictional_team_backgrounds"]
    response = fake_writer.write(task, prompt)
    flavors = {
        "en": "A wholly fictional club legend.",
        "fi": "Täysin kuvitteellinen seuratarina.",
        "bn": "একটি সম্পূর্ণ কাল্পনিক ক্লাব-কাহিনি।",
    }
    for language, flavor in flavors.items():
        if language in response:
            response[language]["fictional_flavor"] = flavor
    return response


async def test_report_is_published_in_three_languages_within_two_minutes(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock.set(KICK_OFF)
    jobs.deferred.clear()
    match = await play_and_finish(db, clock, published_cup)
    names = await analysis.names_for_checking(db, published_cup["tournament_id"])
    corpus = {
        name: {
            "en": "A fictional club legend.",
            "fi": "Täysin kuvitteellinen seuratarina.",
            "bn": "একটি সম্পূর্ণ কাল্পনিক ক্লাব-কাহিনি।",
        }
        for name in names["teams"]
    }
    corpus_path = tmp_path / "team_backgrounds.json"
    corpus_path.write_text(
        json.dumps({"version": 1, "teams": corpus}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(team_backgrounds, "CORPUS_PATH", corpus_path)
    finished_at = clock.now()
    started = time.perf_counter()

    clock.set(finished_at + dt.timedelta(seconds=20))  # the recalc job picks the result up
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    job = next(j for j in deferred("write_story") if j["subject_id"] == str(match.id))
    clock.set(clock.now() + dt.timedelta(seconds=20))  # then the content job runs
    llm = gateway({})
    llm._provider = FakeProvider(responses={"report.v1": report_with_fictional_flavor})
    published = await content.write_story(db, clock, llm, "match", match.id, job["kind"])
    elapsed = time.perf_counter() - started

    assert job["kind"] == "report"
    assert sorted(s.language for s in published) == sorted(LANGUAGES)
    assert all(s.published_at and s.published_at - finished_at < dt.timedelta(minutes=2)
               for s in published)  # fmt: skip
    assert elapsed < 120
    served = api.get(f"/api/v1/matches/{match.id}/stories").json()
    assert {s["language"] for s in served} == set(LANGUAGES)
    assert all(s["author_type"] == "ai" and s["ai_label"] for s in served)
    assert {s["ai_label"] for s in served} == set(content.AI_LABELS.values())
    english_story = next(story for story in served if story["language"] == "en")
    detail = api.get(f"/api/v1/stories/{english_story['id']}").json()
    assert detail["facts"] and all(f["claim"] for f in detail["facts"])
    flavor = next(sentence for sentence in detail["sentences"] if sentence.get("fictional"))
    assert flavor["facts"]
    assert any(fact["id"] == flavor["facts"][0] for fact in detail["facts"])
    assert detail["facts"][-1]["claim"].startswith(
        "Fictional team background (not a match fact): "
    )
    assert "Fictional team flavor (not a match fact)" in detail["body"]
    assert all(
        "fictional" not in sentence["text"].lower()
        for sentence in detail["sentences"]
        if not sentence.get("fictional")
    )
    recheck = await content.check_story(db, UUID(english_story["id"]))
    assert recheck.passed, recheck.issues
    assert api.get(f"/api/v1/tournaments/{published_cup['tournament_id']}/stories?lang=bn").json()


async def test_unchanged_facts_are_not_rewritten(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    provider = FakeProvider(responses=fake_writer.responses())
    llm = gateway({})
    llm._provider = provider  # count the calls of one provider

    first = await content.write_story(db, clock, llm, "match", match.id, "report")
    again = await content.write_story(db, clock, llm, "match", match.id, "report")

    assert len(provider.calls) == 1
    assert {s.id for s in again} == {s.id for s in first}


def wrong_score(task: str, prompt: str) -> dict[str, Any]:
    good = fake_writer.write(task, prompt)
    for text in good.values():
        text["sentences"].insert(0, {"text": "It finished 9-9 in the end.", "facts": ["f1"]})
    return good


async def test_a_draft_that_keeps_failing_the_checker_waits_for_review(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    provider = FakeProvider(responses={"report.v1": wrong_score})
    llm = gateway({})
    llm._provider = provider

    published = await content.write_story(db, clock, llm, "match", match.id, "report")

    assert published == []
    assert len(provider.calls) == 2  # one regeneration with the issues
    assert "9 is not in the cited facts" in provider.calls[1][1]
    assert api.get(f"/api/v1/matches/{match.id}/stories").json() == []


async def test_empty_report_draft_is_rejected_without_crashing(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    provider = FakeProvider(
        responses={
            "report.v1": {
                "en": {"sentences": []},
                "fi": {"sentences": []},
                "bn": {"sentences": []},
            }
        }
    )
    llm = gateway({})
    llm._provider = provider

    published = await content.write_story(db, clock, llm, "match", match.id, "report")

    assert published == []
    assert len(provider.calls) == 2  # gateway retries invalid structured output once
    assert api.get(f"/api/v1/matches/{match.id}/stories").json() == []


async def test_a_second_attempt_that_passes_is_published(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    attempts: list[int] = []

    def flaky(task: str, prompt: str) -> dict[str, Any]:
        attempts.append(1)
        return wrong_score(task, prompt) if len(attempts) == 1 else fake_writer.write(task, prompt)

    published = await content.write_story(
        db, clock, gateway({"report.v1": flaky}), "match", match.id, "report"
    )

    assert len(attempts) == 2
    assert len(published) == 3


async def test_result_announcement_is_drafted_and_sent_by_an_organiser(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    signed_in: dict[str, str],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    tid = published_cup["tournament_id"]
    jobs.deferred.clear()
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, tid)
    job = next(j for j in deferred("draft_announcement") if j["ref"] == str(match.id))

    draft = await content.draft_announcement(
        db, clock, gateway({}), tid, job["kind"], job["ref"]
    )  # no model answer: the template is used
    url = f"/api/v1/tournaments/{tid}/announcements"
    denied = api.get(url)
    await competitions.add_staff(db, tid, UUID(signed_in["user_id"]), "organiser")
    listed = api.get(url)
    sent = api.post(
        f"{url}/{draft.id}/send" if draft else url,
        headers={CSRF_HEADER: signed_in["csrf_token"]},
    )

    assert draft is not None and draft.author_type == "template"
    assert set(draft.texts) == set(LANGUAGES)
    assert draft.texts["bn"].startswith("খেলা শেষ") and "২-১" in draft.texts["bn"]
    assert denied.status_code == 404
    assert listed.status_code == 200 and listed.json()[0]["status"] == "draft"
    assert sent.status_code == 200 and sent.json()["status"] == "sent"


async def test_hub_and_feed_carry_the_team_stories(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    signed_in: dict[str, str],
    gateway: Callable[[dict[str, Any]], LLMGateway],
) -> None:
    clock.set(KICK_OFF)
    match = await play_and_finish(db, clock, published_cup)
    await analysis.recalc_tournament(db, clock, published_cup["tournament_id"])
    await content.write_story(
        db, clock, gateway(fake_writer.responses()), "match", match.id, "report"
    )
    api.post(
        "/api/v1/me/follows",
        json={"target_type": "team", "target_id": str(match.home_team_id), "is_primary": True},
        headers={CSRF_HEADER: signed_in["csrf_token"]},
    )

    hub = api.get(f"/api/v1/me/teams/{match.home_team_id}/hub").json()
    feed = api.get("/api/v1/me/feed").json()

    assert {s["language"] for s in hub["stories"]} == set(LANGUAGES)
    result = next(i for i in feed["items"] if i["kind"] == "result")
    assert {s["kind"] for s in result["stories"]} == {"report"}
