"""GDPR rights: export and delete an account, organisers' participant data requests, and
retention clean-up (docs/09-security-privacy.md, GDPR)."""

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.time import FrozenClock
from app.core.viewer import CSRF_HEADER, Viewer
from app.modules.accounts import service as accounts
from app.modules.audience import service as audience
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import ConsentCreate, PlayerCreate
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn
from app.modules.setup import service as setup


async def test_a_member_exports_and_deletes_their_account(
    api: TestClient, db: AsyncSession, published_cup: dict[str, Any], signed_in: dict[str, str]
) -> None:
    headers = {CSRF_HEADER: signed_in["csrf_token"]}
    team = (await competitions.entries_of(db, published_cup["tournament_id"]))[0].team_id
    api.post(
        "/api/v1/me/follows",
        json={"target_type": "team", "target_id": str(team), "is_primary": True},
        headers=headers,
    )
    user_id = signed_in["user_id"]

    exported = api.post("/api/v1/me/export", headers=headers)
    deleted = api.delete("/api/v1/me", headers=headers)
    after = api.get("/api/v1/me")
    row = (
        await db.execute(
            text("SELECT email, display_name, deleted_at FROM users WHERE id = :id"),
            {"id": user_id},
        )
    ).one()
    left = {
        table: await db.scalar(
            text(f"SELECT count(*) FROM {table} WHERE user_id = :id"), {"id": user_id}
        )
        for table in ("follows", "sessions", "notifications", "push_subscriptions")
    }

    data = exported.json()["data"]
    assert exported.status_code == 200
    assert data["accounts"]["profile"]["email"].startswith("member-")
    assert data["audience"]["follows"][0]["target_id"] == str(team)
    assert set(data) >= {"accounts", "audience", "competitions", "content", "editorial", "scoring"}
    assert deleted.status_code == 204
    assert after.status_code == 401
    assert row.email == f"deleted-{user_id}@deleted.invalid"
    assert row.display_name == "Deleted user" and row.deleted_at is not None
    assert left == dict.fromkeys(left, 0)


def test_data_rights_need_a_signed_in_member(api: TestClient) -> None:
    assert api.post("/api/v1/me/export").status_code == 401
    assert api.delete("/api/v1/me").status_code == 401


async def test_an_organiser_who_scored_matches_can_still_delete_their_account(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    from app.core import privacy
    from app.main import register_privacy

    register_privacy(clock)
    clock.set(dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC))
    owner = Viewer(user_id=published_cup["owner"])
    match = (await competitions.list_matches(db, published_cup["tournament_id"]))[0]
    await scoring.start(db, clock, owner, match.id)
    await scoring.post_event(
        db, clock, owner, match.id, EventIn(client_seq=1, type="goal", team_id=match.home_team_id)
    )

    await privacy.erase_user(db, owner.user_id)  # type: ignore[arg-type]  # set above

    events = await db.scalar(
        text("SELECT count(*) FROM match_events WHERE entered_by_user_id = :id"),
        {"id": owner.user_id},
    )
    staff = await db.scalar(
        text("SELECT count(*) FROM tournament_staff WHERE user_id = :id"), {"id": owner.user_id}
    )
    assert events == 1 and staff == 0  # events stay; the account is a tombstone


async def test_organisers_export_and_erase_participant_data(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any], make_user: Any
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    team = (await competitions.entries_of(db, tid))[0].team_id
    player = await competitions.create_player(
        db,
        clock,
        team,
        PlayerCreate(display_name="Erasable Player", shirt_number=7, birth_year=1990),
    )
    await competitions.record_consent(
        db, clock, player.id, ConsentCreate(scope="profile", guardian_contact="parent-contact")
    )
    stranger = Viewer(user_id=await make_user())

    exported = await competitions.participant_data(db, clock, owner, tid)
    with pytest.raises(NotFound):
        await competitions.participant_data(db, clock, stranger, tid)
    await competitions.erase_player(db, owner, tid, player.id)
    await competitions.erase_team_contact(db, owner, tid, team)
    after = await competitions.participant_data(db, clock, owner, tid)

    before_player = next(p for t in exported.teams for p in t.players if p.id == player.id)
    assert before_player.display_name == "Erasable Player" and before_player.consents
    erased = next(p for t in after.teams for p in t.players if p.id == player.id)
    assert erased.display_name == "Removed player"
    assert erased.birth_year is None and erased.shirt_number is None and not erased.consents
    assert erased.visibility == "hidden"
    erased_team = next(t for t in after.teams if t.id == team)
    assert erased_team.contact_name is None and erased_team.contact_email is None


async def test_retention_removes_what_is_past_its_time(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any], make_user: Any
) -> None:
    user = await make_user()
    await db.execute(
        text(
            "INSERT INTO notifications (id, user_id, kind, team_id, payload, pushed, created_at) "
            "VALUES (gen_random_uuid(), :u, 'result', NULL, '{}', false, :at)"
        ),
        {"u": user, "at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)},
    )
    await db.commit()
    # passes that recorded events stay (events are append-only) but are revoked and scrubbed
    used = "SELECT entered_by_pass_id FROM match_events WHERE entered_by_pass_id IS NOT NULL"
    passes_before = await db.scalar(
        text(f"SELECT count(*) FROM scorer_passes WHERE id NOT IN ({used})")
    )
    intake_before = await db.scalar(text("SELECT count(*) FROM intake_files"))

    clock.set(dt.datetime(2026, 6, 20, tzinfo=dt.UTC))  # a week after the cup
    early = await scoring.purge_passes(db, clock)
    clock.set(dt.datetime(2027, 7, 1, tzinfo=dt.UTC))  # over a year after the cup
    notes = await audience.purge_notifications(db, clock)
    passes = await scoring.purge_passes(db, clock)
    intake = await setup.purge_intake(db, clock)
    tokens = await accounts.purge_expired(db, clock)

    assert early == 0
    assert notes == 1
    assert passes == passes_before and passes > 0
    left = (await db.execute(text("SELECT label, revoked_at FROM scorer_passes"))).all()
    assert all(label == "Expired pass" and revoked for label, revoked in left)
    assert intake == intake_before and intake > 0
    assert tokens >= 0
    assert (
        await db.scalar(text("SELECT count(*) FROM notifications WHERE user_id = :u"), {"u": user})
        == 0
    )
