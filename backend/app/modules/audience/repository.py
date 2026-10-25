"""Audience persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audience.models import Follow, Notification, PushSubscription


async def follows_of(db: AsyncSession, user_id: UUID) -> list[Follow]:
    result = await db.execute(
        select(Follow)
        .where(Follow.user_id == user_id)
        .order_by(Follow.is_primary.desc(), Follow.created_at)
    )
    return list(result.scalars())


async def follow_of(
    db: AsyncSession, user_id: UUID, target_type: str, target_id: UUID
) -> Follow | None:
    result = await db.execute(
        select(Follow).where(
            Follow.user_id == user_id,
            Follow.target_type == target_type,
            Follow.target_id == target_id,
        )
    )
    return result.scalar_one_or_none()


async def clear_primary(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(update(Follow).where(Follow.user_id == user_id).values(is_primary=False))
    await db.flush()


async def followers_of(db: AsyncSession, target_type: str, target_ids: list[UUID]) -> list[Follow]:
    if not target_ids:
        return []
    result = await db.execute(
        select(Follow).where(Follow.target_type == target_type, Follow.target_id.in_(target_ids))
    )
    return list(result.scalars())


async def notified_since(db: AsyncSession, user_id: UUID, team_id: UUID, since: datetime) -> bool:
    result = await db.execute(
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.team_id == team_id,
            Notification.created_at >= since,
        )
        .limit(1)
    )
    return result.first() is not None


async def notifications_of(db: AsyncSession, user_id: UUID, limit: int) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def mark_read(db: AsyncSession, user_id: UUID, ids: list[UUID] | None, now: datetime) -> None:
    query = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if ids is not None:
        query = query.where(Notification.id.in_(ids))
    await db.execute(query.values(read_at=now))


async def has_push(db: AsyncSession, user_id: UUID, endpoint: str) -> bool:
    result = await db.execute(
        select(PushSubscription.id).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    return result.first() is not None


async def purge_notifications(session: AsyncSession, before: datetime) -> int:
    result = await session.execute(delete(Notification).where(Notification.created_at < before))
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult has rowcount


async def notifications_page(
    db: AsyncSession, user_id: UUID, after: tuple[datetime, UUID] | None, limit: int
) -> list[Notification]:
    """Newest first, keyset on (created_at, id)."""
    query = select(Notification).where(Notification.user_id == user_id)
    if after is not None:
        at, last = after
        query = query.where(
            or_(
                Notification.created_at < at,
                and_(Notification.created_at == at, Notification.id < last),
            )
        )
    result = await db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    )
    return list(result)


async def unread_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.scalar(
        select(func.count()).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(result or 0)
