"""Editorial's personal data: corrections a user reported, review work they did."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.editorial.models import Correction, ReviewClaim


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    reported = await db.scalars(select(Correction).where(Correction.reported_by == user_id))
    return {
        "corrections_reported": [
            {
                "story_id": str(c.story_id),
                "text": c.text,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            }
            for c in reported
        ]
    }


async def erase(db: AsyncSession, user_id: UUID) -> None:
    """Reports stay (they were acted on) without the reporter; claims are released."""
    await db.execute(delete(ReviewClaim).where(ReviewClaim.editor_id == user_id))
    for column in (Correction.reported_by, Correction.resolved_by):
        await db.execute(update(Correction).where(column == user_id).values({column.key: None}))


def register() -> None:
    privacy.register("editorial", exporter=export, eraser=erase)
