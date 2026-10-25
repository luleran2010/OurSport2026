"""Content's links to a user: stories they edited, reviewed or announced (anonymised)."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.content.models import Announcement, Story, StoryVersion


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    reviewed = await db.scalar(select(func.count()).where(Story.reviewed_by == user_id))
    edited = await db.scalar(select(func.count()).where(StoryVersion.edited_by == user_id))
    return {"stories_reviewed": reviewed or 0, "story_edits": edited or 0}


async def erase(db: AsyncSession, user_id: UUID) -> None:
    """Authored and reviewed content stays, without the person's name on it."""
    links = (
        (Story, Story.author_user_id),
        (Story, Story.reviewed_by),
        (StoryVersion, StoryVersion.edited_by),
        (Announcement, Announcement.created_by),
    )
    for model, column in links:
        await db.execute(update(model).where(column == user_id).values({column.key: None}))


def register() -> None:
    privacy.register("content", exporter=export, eraser=erase)
