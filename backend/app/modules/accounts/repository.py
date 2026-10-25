"""Accounts persistence. Every function takes the caller's session; no commits here."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.models import (
    AuthSession,
    FamilyLink,
    LoginToken,
    SignupIntent,
    User,
    UserRole,
)


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def roles_of(session: AsyncSession, user_id: UUID) -> frozenset[str]:
    result = await session.execute(select(UserRole.role).where(UserRole.user_id == user_id))
    return frozenset(result.scalars())


async def login_token_by_hash(session: AsyncSession, token_hash: str) -> LoginToken | None:
    result = await session.execute(
        select(LoginToken).where(LoginToken.token_hash == token_hash).with_for_update()
    )
    return result.scalar_one_or_none()


async def intent_for_token(session: AsyncSession, token_id: UUID) -> SignupIntent | None:
    result = await session.execute(
        select(SignupIntent).where(SignupIntent.login_token_id == token_id)
    )
    return result.scalar_one_or_none()


async def session_by_id(session: AsyncSession, session_id: UUID) -> AuthSession | None:
    result = await session.execute(
        select(AuthSession).where(AuthSession.id == session_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def revoke_sessions(session: AsyncSession, user_id: UUID, now: datetime) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def family_player_ids(session: AsyncSession, user_id: UUID) -> frozenset[UUID]:
    result = await session.execute(
        select(FamilyLink.player_id).where(FamilyLink.user_id == user_id)
    )
    return frozenset(result.scalars())


async def users_by_ids(session: AsyncSession, user_ids: list[UUID]) -> list[User]:
    if not user_ids:
        return []
    result = await session.execute(select(User).where(User.id.in_(user_ids)))
    return list(result.scalars())


async def unlink_player(session: AsyncSession, player_id: UUID) -> None:
    await session.execute(delete(FamilyLink).where(FamilyLink.player_id == player_id))


async def purge_expired(session: AsyncSession, now: datetime, *, idle: timedelta) -> int:
    """Login tokens older than a day, expired sign-ups, and sessions ended or idle."""
    removed = 0
    statements = (
        delete(SignupIntent).where(SignupIntent.expires_at < now),
        delete(LoginToken).where(LoginToken.created_at < now - timedelta(days=1)),
        delete(AuthSession).where(
            or_(
                AuthSession.revoked_at < now - timedelta(days=30),
                AuthSession.last_used_at < now - idle,
            )
        ),
    )
    for statement in statements:
        result = await session.execute(statement)
        removed += result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult has rowcount
    return removed
