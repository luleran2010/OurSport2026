"""Rules' links to a user: rulebooks uploaded and rule versions confirmed (anonymised)."""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.rules.models import Rulebook, RuleConfigRecord


async def erase(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(Rulebook).where(Rulebook.uploaded_by == user_id).values(uploaded_by=None)
    )
    await db.execute(
        update(RuleConfigRecord)
        .where(RuleConfigRecord.confirmed_by == user_id)
        .values(confirmed_by=None)
    )


def register() -> None:
    privacy.register("rules", eraser=erase)
