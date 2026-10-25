"""Setup persistence."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.setup.models import (
    DrawRecord,
    IntakeFile,
    SchedulePlanRecord,
    SetupDraft,
    SetupSession,
)


async def session_by_id(db: AsyncSession, session_id: UUID) -> SetupSession | None:
    return await db.get(SetupSession, session_id)


async def files_of(db: AsyncSession, session_id: UUID) -> list[IntakeFile]:
    result = await db.execute(
        select(IntakeFile)
        .where(IntakeFile.setup_session_id == session_id)
        .order_by(IntakeFile.created_at, IntakeFile.id)
    )
    return list(result.scalars())


async def latest_draft(db: AsyncSession, session_id: UUID) -> SetupDraft | None:
    result = await db.execute(
        select(SetupDraft)
        .where(SetupDraft.setup_session_id == session_id, SetupDraft.status != "superseded")
        .order_by(SetupDraft.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def next_draft_version(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        select(func.max(SetupDraft.version)).where(SetupDraft.setup_session_id == session_id)
    )
    return (result.scalar_one() or 0) + 1


async def proposed_draw(db: AsyncSession, tournament_id: UUID) -> DrawRecord | None:
    result = await db.execute(
        select(DrawRecord)
        .where(DrawRecord.tournament_id == tournament_id, DrawRecord.status == "proposed")
        .order_by(DrawRecord.created_at.desc(), DrawRecord.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_draw(db: AsyncSession, tournament_id: UUID) -> DrawRecord | None:
    result = await db.execute(
        select(DrawRecord)
        .where(DrawRecord.tournament_id == tournament_id, DrawRecord.status != "discarded")
        .order_by(DrawRecord.created_at.desc(), DrawRecord.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def proposed_plan(db: AsyncSession, tournament_id: UUID) -> SchedulePlanRecord | None:
    result = await db.execute(
        select(SchedulePlanRecord)
        .where(
            SchedulePlanRecord.tournament_id == tournament_id,
            SchedulePlanRecord.status == "proposed",
        )
        .order_by(SchedulePlanRecord.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_plan(db: AsyncSession, tournament_id: UUID) -> SchedulePlanRecord | None:
    result = await db.execute(
        select(SchedulePlanRecord)
        .where(
            SchedulePlanRecord.tournament_id == tournament_id,
            SchedulePlanRecord.status != "superseded",
        )
        .order_by(SchedulePlanRecord.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def next_plan_version(db: AsyncSession, tournament_id: UUID) -> int:
    result = await db.execute(
        select(func.max(SchedulePlanRecord.version)).where(
            SchedulePlanRecord.tournament_id == tournament_id
        )
    )
    return (result.scalar_one() or 0) + 1


async def published_draw(db: AsyncSession, tournament_id: UUID) -> DrawRecord | None:
    result = await db.execute(
        select(DrawRecord).where(
            DrawRecord.tournament_id == tournament_id, DrawRecord.status == "published"
        )
    )
    return result.scalar_one_or_none()


async def published_plan(db: AsyncSession, tournament_id: UUID) -> SchedulePlanRecord | None:
    result = await db.execute(
        select(SchedulePlanRecord)
        .where(
            SchedulePlanRecord.tournament_id == tournament_id,
            SchedulePlanRecord.status == "published",
        )
        .order_by(SchedulePlanRecord.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def intake_tournaments(session: AsyncSession) -> list[UUID]:
    result = await session.scalars(
        select(SetupSession.tournament_id)
        .join(IntakeFile, IntakeFile.setup_session_id == SetupSession.id)
        .distinct()
    )
    return list(result)


async def delete_intake(session: AsyncSession, tournament_id: UUID) -> int:
    sessions = select(SetupSession.id).where(SetupSession.tournament_id == tournament_id)
    result = await session.execute(
        delete(IntakeFile).where(IntakeFile.setup_session_id.in_(sessions))
    )
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult has rowcount


async def sessions_of_tournaments(
    db: AsyncSession, tournament_ids: list[UUID]
) -> list[SetupSession]:
    """Setup sessions of these tournaments, most recently changed first."""
    if not tournament_ids:
        return []
    result = await db.scalars(
        select(SetupSession)
        .where(SetupSession.tournament_id.in_(tournament_ids))
        .order_by(SetupSession.updated_at.desc())
    )
    return list(result)
