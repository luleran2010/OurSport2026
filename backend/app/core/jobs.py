"""Background jobs on Procrastinate (ADR 0002, docs/08-jobs.md).

`defer` writes the job row with Procrastinate's own SQL function on the caller's SQLAlchemy
session, so the job commits or rolls back with the data change that caused it. The worker
(`app.worker`) runs the jobs with Procrastinate's psycopg connector.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.viewer import CurrentViewer

log = structlog.get_logger("jobs")

QUEUES: Final = ("setup", "engine", "content", "media", "notify", "imports", "periodic")
JOB_QUEUES: Final[dict[str, str]] = {
    "extract_setup": "setup",
    "generate_draw_and_schedule": "setup",
    "publish_setup_followups": "setup",
    "recalc_live": "engine",
    "recalc_tournament": "engine",
    "prematch_build": "engine",
    "write_commentary": "content",
    "write_story": "content",
    "render_printables": "media",
    "notify_followers": "notify",
    "notify_teams": "notify",
    "send_email": "notify",
}
_DEFER = text(
    "SELECT unnest(procrastinate_defer_jobs_v1(ARRAY[ROW("
    ":queue, :task, 0, NULL, NULL, CAST(:args AS jsonb), CAST(:run_at AS timestamptz)"
    ")::procrastinate_job_to_defer_v1])) AS id"
)


@dataclass(frozen=True)
class DeferredJob:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    run_at: datetime | None = None


deferred: list[DeferredJob] = []  # what this process deferred (for tests and debugging)


async def defer(
    session: AsyncSession,
    name: str,
    *,
    queue: str | None = None,
    run_at: datetime | None = None,
    **args: Any,
) -> int:
    """Enqueue job `name` in the caller's transaction (not before `run_at`); returns its id."""
    payload = json.dumps(
        {k: v if isinstance(v, int | float | bool) else str(v) for k, v in args.items()}
    )
    queue = queue or JOB_QUEUES.get(name, "engine")
    params = {"queue": queue, "task": name, "args": payload, "run_at": run_at}
    result = await session.execute(_DEFER, params)
    job_id = int(result.scalar_one())
    deferred.append(DeferredJob(name, args, job_id, run_at))
    log.info("job_deferred", job=name, queue=queue, id=job_id)
    return job_id


# --- admin -----------------------------------------------------------------------------------


class FailedJob(BaseModel):
    id: int
    task_name: str
    queue_name: str
    args: dict[str, Any]
    attempts: int
    scheduled_at: datetime | None


router = APIRouter(prefix="/admin/jobs", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_session)]


def _require_admin(viewer: CurrentViewer) -> None:
    if "platform_admin" not in viewer.global_roles:
        raise NotFound()  # not even the existence of the admin area is shown


@router.get("/failed", response_model=list[FailedJob], operation_id="listFailedJobs")
async def failed_jobs(viewer: CurrentViewer, db: Db) -> list[FailedJob]:
    """Jobs that ran out of retries (platform admins)."""
    _require_admin(viewer)
    rows = await db.execute(
        text(
            "SELECT id, task_name, queue_name, args, attempts, scheduled_at "
            "FROM procrastinate_jobs WHERE status = 'failed' ORDER BY id DESC LIMIT 200"
        )
    )
    return [FailedJob.model_validate(dict(r._mapping)) for r in rows]


@router.post("/{job_id}/retry", status_code=204, operation_id="retryJob")
async def retry_job(job_id: int, viewer: CurrentViewer, db: Db) -> None:
    """Put a failed job back in its queue (platform admins)."""
    _require_admin(viewer)
    async with db.begin():
        await db.execute(
            text("SELECT procrastinate_retry_job_v2(:id, now(), NULL, NULL, NULL)"), {"id": job_id}
        )
