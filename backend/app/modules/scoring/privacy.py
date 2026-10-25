"""Scoring's links to a user. Match events are append-only and keep `entered_by_user_id`;
the account itself becomes an anonymous tombstone (accounts), so no personal data stays."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.scoring.models import MatchEvent, ScorerPass


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    events = await db.scalar(select(func.count()).where(MatchEvent.entered_by_user_id == user_id))
    return {"match_events_entered": events or 0}


async def erase(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(ScorerPass).where(ScorerPass.created_by == user_id).values(created_by=None)
    )


def register() -> None:
    privacy.register("scoring", exporter=export, eraser=erase)
