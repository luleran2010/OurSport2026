"""Audience's personal data: follows, notifications and push subscriptions."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.audience.models import Follow, Notification, PushSubscription


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    follows = await db.scalars(select(Follow).where(Follow.user_id == user_id))
    notes = await db.scalars(select(Notification).where(Notification.user_id == user_id))
    pushes = await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
    return {
        "follows": [
            {
                "target_type": f.target_type,
                "target_id": str(f.target_id),
                "is_primary": f.is_primary,
                "notify": f.notify,
            }
            for f in follows
        ],
        "notifications": [
            {"kind": n.kind, "payload": n.payload, "created_at": n.created_at.isoformat()}
            for n in notes
        ],
        "push_subscriptions": [
            {"endpoint": p.endpoint, "created_at": p.created_at.isoformat()} for p in pushes
        ],
    }


async def erase(db: AsyncSession, user_id: UUID) -> None:
    for model in (Follow, Notification, PushSubscription):
        await db.execute(delete(model).where(model.user_id == user_id))


def register() -> None:
    privacy.register("audience", exporter=export, eraser=erase)
