"""The Procrastinate worker app: `uv run procrastinate --app=app.worker.app worker`.

Job functions live in the modules that own the work; this file only registers them and
the periodic schedule (docs/08-jobs.md). Jobs whose module arrives later only log.
"""

import asyncio
import sys
from functools import cache
from typing import Any
from uuid import UUID

import structlog
from procrastinate import App, PsycopgConnector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.email import SmtpEmailSender
from app.core.live import LiveHub
from app.core.llm import LLMGateway, build_gateway
from app.core.redis_client import create_redis
from app.core.time import SystemClock
from app.modules.accounts import service as accounts
from app.modules.analysis import service as analysis
from app.modules.audience import notifications
from app.modules.audience import service as audience
from app.modules.competitions import service as competitions
from app.modules.content import commentary, fake_writer
from app.modules.content import service as content
from app.modules.scoring import service as scoring
from app.modules.setup import service as setup

log = structlog.get_logger("worker")


def _conninfo() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


app = App(connector=PsycopgConnector(conninfo=_conninfo()))


def _placeholder(name: str, queue: str, retries: int = 0) -> None:
    @app.task(name=name, queue=queue, retry=retries)
    async def run(**args: Any) -> None:
        log.info("job_ran", job=name, args=args)

    del run


@cache
def _sessions() -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(create_engine(get_settings()))


@cache
def _llm() -> LLMGateway:
    settings = get_settings()
    return build_gateway(
        settings, create_redis(settings), SystemClock(), fake_writer.provider_for(settings)
    )


@app.task(name="write_story", queue="content", retry=3)
async def write_story(
    subject_type: str,
    subject_id: str,
    kind: str,
    tournament_id: str | None = None,
    correction: bool = False,
    **_: Any,
) -> None:
    async with _sessions()() as db:
        published = await content.write_story(
            db,
            SystemClock(),
            _llm(),
            subject_type,
            UUID(subject_id),
            kind,
            tournament_id=UUID(tournament_id) if tournament_id else None,
            correction=bool(correction),
            live=_live(),
        )
    log.info("write_story", kind=kind, subject_id=subject_id, published=len(published))


@cache
def _live() -> LiveHub:
    return LiveHub(create_redis(get_settings()))


@app.task(name="write_commentary", queue="content", retry=0)
async def write_commentary(match_id: str, seq: int, moments: str = "", **_: Any) -> None:
    async with _sessions()() as db:
        await commentary.write_commentary(
            db, SystemClock(), _llm(), _live(), UUID(match_id), int(seq),
            [m for m in moments.split(",") if m],
        )  # fmt: skip


@app.task(name="refresh_team_content", queue="content", retry=3)
async def refresh_team_content(tournament_id: str, team_id: str, **_: Any) -> None:
    async with _sessions()() as db:
        changed = await content.refresh_team_content(
            db, SystemClock(), _llm(), UUID(tournament_id), UUID(team_id)
        )
    log.info("refresh_team_content", team_id=team_id, changed=changed)


@app.task(name="draft_announcement", queue="content", retry=2)
async def draft_announcement(tournament_id: str, kind: str, ref: str, **_: Any) -> None:
    async with _sessions()() as db:
        await content.draft_announcement(db, SystemClock(), _llm(), UUID(tournament_id), kind, ref)


@app.task(name="recalc_tournament", queue="engine", retry=3)
async def recalc_tournament(tournament_id: str, **_: Any) -> None:
    async with _sessions()() as db:
        ran = await analysis.recalc_tournament(db, SystemClock(), UUID(tournament_id))
    log.info("recalc_tournament", tournament_id=tournament_id, computed=ran)


@app.task(name="recalc_live", queue="engine", retry=2)
async def recalc_live(match_id: str, seq: int, **_: Any) -> None:
    async with _sessions()() as db:
        await analysis.recalc_live(db, SystemClock(), UUID(match_id), int(seq))


for _name, _queue, _retries in (
    ("prematch_build", "engine", 3),
    ("notify_teams", "notify", 3),
):
    _placeholder(_name, _queue, _retries)


@app.task(name="notify_followers", queue="notify", retry=3)
async def notify_followers(**args: Any) -> None:
    settings = get_settings()
    delivery = notifications.delivery_for(settings, SmtpEmailSender(settings))
    async with _sessions()() as db:
        created = await notifications.handle_job(db, SystemClock(), delivery, args)
    log.info("notified", kind=args.get("kind"), created=created)


@app.periodic(cron="*/5 * * * *")
@app.task(name="match_reminders", queue="periodic")
async def match_reminders(timestamp: int) -> None:
    settings = get_settings()
    delivery = notifications.delivery_for(settings, SmtpEmailSender(settings))
    async with _sessions()() as db:
        sent = await notifications.reminders(db, SystemClock(), delivery)
    log.info("periodic", task="match_reminders", at=timestamp, sent=sent)


@app.periodic(cron="*/10 * * * *")
@app.task(name="prematch_sweep", queue="periodic")
async def prematch_sweep(timestamp: int) -> None:
    log.info("periodic", task="prematch_sweep", at=timestamp)


@app.periodic(cron="*/5 * * * *")
@app.task(name="lifecycle_transitions", queue="periodic")
async def lifecycle_transitions(timestamp: int) -> None:
    async with _sessions()() as db:
        moved = await competitions.lifecycle_transitions(db, SystemClock())
    log.info("periodic", task="lifecycle_transitions", at=timestamp, moved=moved)


@app.periodic(cron="30 3 * * *")
@app.task(name="cleanup", queue="periodic")
async def cleanup(timestamp: int) -> None:
    """Retention (docs/09-security-privacy.md, GDPR)."""
    clock = SystemClock()
    async with _sessions()() as db:
        removed = {
            "accounts": await accounts.purge_expired(db, clock),
            "notifications": await audience.purge_notifications(db, clock),
            "scorer_passes": await scoring.purge_passes(db, clock),
            "intake_files": await setup.purge_intake(db, clock),
        }
    log.info("periodic", task="cleanup", at=timestamp, removed=removed)


def main() -> None:
    """`uv run python -m app.worker`: the worker, also on Windows, where psycopg needs the
    selector event loop (the `procrastinate` command starts the default one)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def run() -> None:
        async with app.open_async():
            await app.run_worker_async()

    asyncio.run(run())


if __name__ == "__main__":
    main()
