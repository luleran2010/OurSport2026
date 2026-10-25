"""Compliance flows (docs/13 §7): processing terms before uploads, consent preferences,
legal pages, notice and action with reasons, rosters with junior consents, and content
refreshed when a player may no longer be named."""

import datetime as dt
import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.config import Settings
from app.core.errors import NotFound, ProcessingAgreementRequired, ValidationFailed
from app.core.llm import FakeProvider, LLMGateway
from app.core.security import AccessClaims, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import ConsentCreate, OrganisationCreate, PlayerCreate
from app.modules.content import fake_writer
from app.modules.content import service as content
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn
from app.modules.setup import service as setup
from app.modules.setup.schemas import SetupStart

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
SECRET = "test-secret-not-for-real-use-0123456789abcdef"


def sign_in(
    api: TestClient, clock: FrozenClock, user_id: UUID, roles: frozenset[str]
) -> dict[str, str]:
    claims = AccessClaims(user_id, uuid4(), roles, clock.now() + dt.timedelta(minutes=10))
    api.cookies.set(ACCESS_COOKIE, encode_access_token(claims, SECRET))
    api.cookies.set(CSRF_COOKIE, "csrf-test-token")
    return {CSRF_HEADER: "csrf-test-token"}


async def test_uploads_wait_for_the_processing_terms(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]]
) -> None:
    viewer = Viewer(user_id=await make_user())
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="club", name="Terms FC", sports=["football"], accept_processing_terms=True
        ),
    )
    await db.execute(
        text("DELETE FROM processing_agreements WHERE organisation_id = :o"), {"o": org.id}
    )
    await db.commit()
    session = await setup.start(
        db, clock, viewer, SetupStart(organisation_id=org.id, name="Terms Cup", sport="football")
    )
    upload = {
        "kind": "rulebook",
        "filename": "rules.txt",
        "mime": "text/plain",
        "data": b"Win 3 points, draw 1 point.",
    }

    with pytest.raises(ProcessingAgreementRequired):
        await setup.add_file(db, clock, viewer, session.id, **upload)  # type: ignore[arg-type]
    with pytest.raises(NotFound):
        await competitions.accept_processing_agreement(
            db, clock, Viewer(user_id=await make_user()), org.id
        )
    accepted = await competitions.accept_processing_agreement(db, clock, viewer, org.id)
    added = await setup.add_file(db, clock, viewer, session.id, **upload)  # type: ignore[arg-type]

    assert accepted.version == competitions.PROCESSING_TERMS_VERSION
    assert added.kind == "rulebook"


async def test_members_choose_cookies_and_marketing_and_can_change_it(
    api: TestClient, signed_in: dict[str, str]
) -> None:
    headers = {CSRF_HEADER: signed_in["csrf_token"]}
    before = api.get("/api/v1/me").json()["preferences"]
    changed = api.patch(
        "/api/v1/me", json={"preferences": {"analytics_cookies": True}}, headers=headers
    ).json()["preferences"]

    assert before == {"analytics_cookies": False, "marketing_emails": False, "updated_at": None}
    assert changed["analytics_cookies"] is True and changed["marketing_emails"] is False
    assert changed["updated_at"]


def test_legal_pages_exist_in_every_language(api: TestClient) -> None:
    for document in ("privacy", "cookies", "accessibility", "ai", "contact"):
        for lang in ("fi", "en", "bn"):
            page = api.get(f"/api/v1/legal/{document}?lang={lang}")
            assert page.status_code == 200, (document, lang)
            assert page.json()["language"] == lang and page.json()["markdown"].startswith("# ")
    assert api.get("/api/v1/legal/terms-of-war").status_code == 422
    bengali = api.get("/api/v1/legal/privacy?lang=bn").json()["markdown"]
    assert "গোপনীয়তা" in bengali


@pytest.fixture
async def gateway(make_settings: Callable[..., Settings], clock: FrozenClock) -> Any:
    redis = Redis.from_url(os.environ["REDIS_URL"])
    await redis.flushdb()
    yield LLMGateway(FakeProvider(responses=fake_writer.responses()), make_settings(), redis, clock)
    await redis.aclose()


async def finished_with_scorer(
    db: AsyncSession, clock: FrozenClock, cup: dict[str, Any], llm: LLMGateway
) -> tuple[Any, Any]:
    """A finished match whose public scorer is named in the report."""
    tid = cup["tournament_id"]
    owner = Viewer(user_id=cup["owner"])
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    assert match.home_team_id
    scorer = await competitions.create_player(
        db, clock, match.home_team_id, PlayerCreate(display_name="Named Scorer")
    )
    await scoring.start(db, clock, owner, match.id)
    await scoring.post_event(
        db,
        clock,
        owner,
        match.id,
        EventIn(
            client_seq=1,
            type="goal",
            team_id=match.home_team_id,
            player_id=scorer.id,
            clock="12:00",
        ),
    )
    await scoring.finish(db, clock, owner, match.id, 1, 0)
    await analysis.recalc_tournament(db, clock, tid)
    await content.write_story(db, clock, llm, "match", match.id, "report")
    return match, scorer


async def test_reports_are_answered_with_a_statement_of_reasons(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: LLMGateway,
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    clock.set(KICK_OFF)
    match, _ = await finished_with_scorer(db, clock, published_cup, gateway)
    story = api.get(f"/api/v1/matches/{match.id}/stories?lang=en").json()[0]
    reader, editor = await make_user(), await make_user()

    headers = sign_in(api, clock, reader, frozenset())
    api.post(
        f"/api/v1/stories/{story['id']}/corrections",
        json={"kind": "privacy", "text": "Please remove my name."},
        headers=headers,
    )
    headers = sign_in(api, clock, editor, frozenset({"editor"}))
    no_reason = api.post(f"/api/v1/stories/{story['id']}/unpublish", json={}, headers=headers)
    removed = api.post(
        f"/api/v1/stories/{story['id']}/unpublish",
        json={"reason": "Removed at the player's request."},
        headers=headers,
    )
    sign_in(api, clock, reader, frozenset())
    reports = api.get("/api/v1/me/reports").json()

    assert no_reason.status_code == 422
    assert removed.status_code == 200 and removed.json()["status"] == "unpublished"
    assert reports[0]["kind"] == "privacy" and reports[0]["status"] == "fixed"
    assert reports[0]["note"] == "Removed at the player's request."
    assert story["id"] not in {
        s["id"] for s in api.get(f"/api/v1/matches/{match.id}/stories").json()
    }


async def test_organisers_manage_rosters_consents_and_guardians(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    team = (await competitions.entries_of(db, tid))[0].team_id
    stranger = Viewer(user_id=await make_user())
    jobs.deferred.clear()

    junior = await competitions.add_roster_player(
        db, clock, owner, tid, team, PlayerCreate(display_name="Young Talent", birth_year=2014)
    )
    with pytest.raises(ValidationFailed):
        await competitions.change_visibility(db, clock, owner, tid, junior.id, "public")
    for scope in ("profile", "stats"):
        await competitions.add_consent(
            db,
            clock,
            owner,
            tid,
            junior.id,
            ConsentCreate(scope=scope, guardian_contact="guardian"),
        )
    public = await competitions.change_visibility(db, clock, owner, tid, junior.id, "public")
    roster = await competitions.roster(db, owner, tid, team)
    stats = next(c for p in roster if p.id == junior.id for c in p.consents if c.scope == "stats")
    lowered = await competitions.remove_consent(db, clock, owner, tid, stats.id)
    guardian = await make_user()
    email = await db.scalar(text("SELECT email FROM users WHERE id = :u"), {"u": guardian})
    await competitions.link_guardian(db, clock, owner, tid, junior.id, str(email))
    with pytest.raises(NotFound):
        await competitions.roster(db, stranger, tid, team)

    assert junior.visibility == "hidden" and public.visibility == "public"
    assert lowered.visibility == "family_only"
    assert any(j.name == "refresh_team_content" for j in jobs.deferred)
    links = await db.scalar(
        text("SELECT count(*) FROM family_links WHERE player_id = :p"), {"p": junior.id}
    )
    assert links == 1


async def test_a_player_who_may_no_longer_be_named_disappears_from_content(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    gateway: LLMGateway,
) -> None:
    clock.set(KICK_OFF)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    match, scorer = await finished_with_scorer(db, clock, published_cup, gateway)
    own = {"t": tid}  # earlier tests' tournaments stay in the database
    before = await db.scalar(
        text("SELECT string_agg(body, ' ') FROM stories WHERE tournament_id = :t"), own
    )

    await competitions.change_visibility(db, clock, owner, tid, scorer.id, "hidden")
    changed = await content.refresh_team_content(db, clock, gateway, tid, match.home_team_id)
    after = await db.scalar(
        text(
            "SELECT string_agg(body || sentences::text, ' ') FROM stories WHERE tournament_id = :t"
        ),
        own,
    )

    assert before and "Named Scorer" in before
    assert changed > 0
    assert after and "Named Scorer" not in after
