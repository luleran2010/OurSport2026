"""Printables, share cards and the venue screen rotation (T-063)."""

import datetime as dt
import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm import FakeProvider, LLMGateway
from app.core.security import AccessClaims, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.content import commentary, fake_writer
from app.modules.content import service as content
from app.modules.media import service as media
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
SECRET = "test-secret-not-for-real-use-0123456789abcdef"


def sign_in(api: TestClient, clock: FrozenClock, user_id: UUID) -> None:
    claims = AccessClaims(user_id, uuid4(), frozenset(), clock.now() + dt.timedelta(minutes=10))
    api.cookies.set(ACCESS_COOKIE, encode_access_token(claims, SECRET))


async def test_pitch_sheets_carry_each_pitch_qr_and_its_matches(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    tid = published_cup["tournament_id"]
    url = f"/api/v1/tournaments/{tid}/printables/pitch-sheets"
    anonymous = api.get(url)
    sign_in(api, clock, await make_user())
    stranger = api.get(url)
    sign_in(api, clock, published_cup["owner"])
    sheets = api.get(url)
    notice_before = api.get(f"/api/v1/tournaments/{tid}/printables/filming-notice")
    await media.publish_notice(db, clock, Viewer(user_id=published_cup["owner"]), tid)
    notice = api.get(f"/api/v1/tournaments/{tid}/printables/filming-notice")

    assert anonymous.status_code == 401 and stranger.status_code == 403
    assert sheets.status_code == 200 and sheets.headers["content-type"].startswith("text/html")
    html = sheets.text
    assert html.count('class="sheet"') == 4 and html.count("<svg") == 4
    assert "A1" in html and "Kirjurin passi" in html
    assert notice_before.status_code == 404
    assert notice.status_code == 200 and "otteluita voidaan kuvata" in notice.text


async def test_share_cards_show_the_match_and_label_ai_stories(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_settings: Callable[..., Settings],
) -> None:
    clock.set(KICK_OFF)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    await analysis.recalc_tournament(db, clock, tid)
    match = (await competitions.list_matches(db, tid))[0]
    await scoring.enter_result(db, clock, owner, match.id, _result(2, 1))
    await analysis.recalc_tournament(db, clock, tid)
    redis = Redis.from_url(os.environ["REDIS_URL"])
    await redis.flushdb()
    llm = LLMGateway(FakeProvider(responses=fake_writer.responses()), make_settings(), redis, clock)
    [story, *_] = await content.write_story(db, clock, llm, "match", match.id, "report")
    await redis.aclose()

    card = api.get(f"/api/v1/cards/matches/{match.id}.svg")
    story_card = api.get(f"/api/v1/cards/stories/{story.id}.svg")
    missing = api.get(f"/api/v1/cards/stories/{uuid4()}.svg")

    assert card.status_code == 200 and card.headers["content-type"] == "image/svg+xml"
    assert "2 - 1" in card.text and 'width="1200"' in card.text
    assert story_card.status_code == 200
    assert ("AI-written" in story_card.text) or ("Tekoälyn kirjoittama" in story_card.text)
    assert missing.status_code == 404


def _result(home: int, away: int) -> Any:
    from app.modules.scoring.schemas import ResultIn

    return ResultIn(home_goals=home, away_goals=away)


async def test_the_screen_rotates_live_commentary_tables_and_announcements(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_settings: Callable[..., Settings],
) -> None:
    clock.set(KICK_OFF + dt.timedelta(minutes=5))
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    await analysis.recalc_tournament(db, clock, tid)
    live = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    redis = Redis.from_url(os.environ["REDIS_URL"])
    await redis.flushdb()
    llm = LLMGateway(FakeProvider(responses=fake_writer.responses()), make_settings(), redis, clock)
    await scoring.start(db, clock, owner, live.id)
    goal = await scoring.post_event(
        db, clock, owner, live.id, EventIn(client_seq=1, type="goal", team_id=live.home_team_id)
    )
    await commentary.write_commentary(db, clock, llm, None, live.id, goal.seq, goal.moments)
    other = next(m for m in await competitions.list_matches(db, tid) if m.id != live.id)
    await scoring.enter_result(db, clock, owner, other.id, _result(1, 0))
    await analysis.recalc_tournament(db, clock, tid)
    draft = await content.draft_announcement(db, clock, llm, tid, "result", str(other.id))
    assert draft is not None
    from app.core.live import LiveHub

    hub = LiveHub(redis)
    await content.send_announcement(db, clock, owner, tid, draft.id, hub)
    await hub.close()
    await redis.aclose()

    rotation = api.get(f"/api/v1/tournaments/{tid}/screen/rotation").json()

    kinds = [p["kind"] for p in rotation["panels"]]
    assert kinds[0] == "now_playing"
    assert {"commentary", "next_up", "standings", "announcement"} <= set(kinds)
    assert kinds.count("standings") == 4
    line = next(p for p in rotation["panels"] if p["kind"] == "commentary")["data"]["lines"][0]
    assert line["items"] and line["author_type"] in ("ai", "template")
