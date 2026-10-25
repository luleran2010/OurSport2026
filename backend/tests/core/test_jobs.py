from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from procrastinate import App, PsycopgConnector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.security import AccessClaims, encode_access_token
from app.core.time import FrozenClock
from app.core.viewer import ACCESS_COOKIE


async def jobs_in(db: AsyncSession, queue: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT id, task_name, status, args FROM procrastinate_jobs WHERE queue_name = :q"),
        {"q": queue},
    )
    return [dict(r._mapping) for r in rows]


async def test_a_job_deferred_in_a_rolled_back_transaction_never_exists(db: AsyncSession) -> None:
    queue = f"test-{uuid4().hex[:8]}"

    await db.begin()
    await jobs.defer(db, "probe", queue=queue, n=1)
    await db.rollback()

    assert await jobs_in(db, queue) == []


async def test_a_committed_job_always_runs(db: AsyncSession, database_url: str) -> None:
    queue = f"test-{uuid4().hex[:8]}"
    ran: list[dict[str, Any]] = []
    async with db.begin():
        await jobs.defer(db, "probe", queue=queue, n=7)
    conninfo = database_url.replace("postgresql+asyncpg://", "postgresql://")
    worker = App(connector=PsycopgConnector(conninfo=conninfo))

    @worker.task(name="probe", queue=queue)
    async def probe(**args: Any) -> None:
        ran.append(args)

    async with worker.open_async():
        await worker.run_worker_async(queues=[queue], wait=False)

    assert ran == [{"n": 7}]
    assert [j["status"] for j in await jobs_in(db, queue)] == ["succeeded"]


def admin_cookie(clock: FrozenClock, roles: frozenset[str]) -> str:
    from datetime import timedelta

    claims = AccessClaims(uuid4(), uuid4(), roles, clock.now() + timedelta(minutes=10))
    return encode_access_token(claims, "test-secret-not-for-real-use-0123456789abcdef")


def test_failed_jobs_are_for_platform_admins_only(
    api: TestClient, clock: FrozenClock, make_settings: Callable[..., Any]
) -> None:
    api.cookies.set(ACCESS_COOKIE, admin_cookie(clock, frozenset()))
    denied = api.get("/api/v1/admin/jobs/failed")
    api.cookies.set(ACCESS_COOKIE, admin_cookie(clock, frozenset({"platform_admin"})))
    allowed = api.get("/api/v1/admin/jobs/failed")

    assert denied.status_code == 404
    assert allowed.status_code == 200
    assert isinstance(allowed.json(), list)
