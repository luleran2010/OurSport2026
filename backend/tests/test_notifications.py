"""Following a team: every kind of notification, quiet hours, the 2-hour exception."""

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.pagination import PageParams
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.audience import notifications
from app.modules.audience import service as audience
from app.modules.audience.schemas import FollowIn, PushKeys, PushSubscriptionIn
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import ResultIn

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)  # 10:00 Helsinki
LATE_EVENING = dt.datetime(2026, 6, 12, 20, 30, tzinfo=dt.UTC)  # 23:30 Helsinki


class RecordingPush:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, endpoint: str, keys: dict[str, str], payload: dict[str, Any]) -> bool:
        self.sent.append(payload)
        return True


async def fan_of(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], team: UUID
) -> Viewer:
    fan = Viewer(user_id=await make_user())
    await audience.follow(
        db, clock, fan, FollowIn(target_type="team", target_id=team, is_primary=True)
    )
    await audience.add_push_subscription(
        db,
        clock,
        fan,
        PushSubscriptionIn(
            endpoint="https://push.example.com/abc", keys=PushKeys(p256dh="k", auth="a")
        ),
    )
    return fan


async def run_deferred(
    db: AsyncSession, clock: FrozenClock, delivery: notifications.Delivery
) -> None:
    pending = [j for j in jobs.deferred if j.name == "notify_followers"]
    jobs.deferred.clear()
    for job in pending:
        await notifications.handle_job(db, clock, delivery, job.args)
        clock.advance(dt.timedelta(minutes=6))  # past the 5-minute limit per team


async def test_following_a_team_brings_every_kind_of_notification(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    entries = await competitions.entries_of(db, tid)
    strength = {e.team_id: -(e.seed or 0) for e in entries}
    favourite = max(strength, key=strength.__getitem__)
    fan = await fan_of(db, clock, make_user, favourite)
    push = RecordingPush()
    delivery = notifications.Delivery(push=push)
    await analysis.recalc_tournament(db, clock, tid)  # baseline before any result
    jobs.deferred.clear()

    matches = await competitions.list_matches(db, tid)
    first = next(
        m for m in matches if m.stage == "group" and favourite in (m.home_team_id, m.away_team_id)
    )
    await scoring.start(db, clock, owner, first.id)
    for m in (m for m in matches if m.stage == "group"):
        assert m.home_team_id and m.away_team_id
        home_wins = strength[m.home_team_id] > strength[m.away_team_id]
        await scoring.enter_result(
            db,
            clock,
            owner,
            m.id,
            ResultIn(home_goals=2 if home_wins else 0, away_goals=0 if home_wins else 1),
        )
    await analysis.recalc_tournament(db, clock, tid)
    await run_deferred(db, clock, delivery)
    for kind, extra in (
        ("schedule_change", {}),
        ("relevance", {"reason": "Best for you: a draw."}),
    ):
        await notifications.handle_job(
            db,
            clock,
            delivery,
            {"kind": kind, "tournament_id": tid, "team_ids": str(favourite), **extra},
        )
        clock.advance(dt.timedelta(minutes=6))

    kinds = {
        n.kind for n in (await audience.my_notifications(db, fan, PageParams(limit=200))).items
    }
    assert kinds >= {
        "match_start",
        "result",
        "scenario_change",
        "relevance",
        "schedule_change",
        "next_opponent",
    }
    texts = [
        n.text for n in (await audience.my_notifications(db, fan, PageParams(limit=200))).items
    ]
    assert any(t.startswith("Full time:") for t in texts)
    assert push.sent, "pushed outside quiet hours"


async def test_quiet_hours_hold_back_pushes_except_urgent_schedule_changes(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    tid = published_cup["tournament_id"]
    team = (await competitions.entries_of(db, tid))[0].team_id
    fan = await fan_of(db, clock, make_user, team)
    push = RecordingPush()
    delivery = notifications.Delivery(push=push)
    clock.set(LATE_EVENING)

    await notifications.handle_job(
        db,
        clock,
        delivery,
        {
            "kind": "scenario_change",
            "tournament_id": tid,
            "team_ids": str(team),
            "summary": "Win: through.",
        },
    )
    soon = (LATE_EVENING + dt.timedelta(minutes=90)).isoformat()
    await notifications.handle_job(
        db,
        clock,
        delivery,
        {"kind": "schedule_change", "tournament_id": tid, "team_ids": str(team), "starts_at": soon},
    )

    rows = {n.kind: n for n in (await audience.my_notifications(db, fan, PageParams())).items}
    assert set(rows) == {"scenario_change", "schedule_change"}  # both wait in the app
    assert [p["kind"] for p in push.sent] == ["schedule_change"]  # only the urgent one pushed


async def test_opting_out_of_a_kind(
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
) -> None:
    from app.modules.audience.schemas import NotifyPatch

    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    team = (await competitions.entries_of(db, tid))[0].team_id
    fan = await fan_of(db, clock, make_user, team)
    follow = (await audience.list_follows(db, fan))[0]
    await audience.set_notifications(db, fan, follow.id, NotifyPatch(scenario_change=False))

    created = await notifications.handle_job(
        db,
        clock,
        notifications.Delivery(),
        {"kind": "scenario_change", "tournament_id": tid, "team_ids": str(team), "summary": "x"},
    )

    assert created == 0
