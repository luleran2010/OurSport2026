"""Accounts' personal data and the account erasure itself (runs after every module).

The user row is kept as an anonymous tombstone (no email, name or settings of the person)
because append-only match events and setup sessions point at it; everything else about
the account is deleted.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.core.time import Clock
from app.modules.accounts.models import (
    AuthSession,
    FamilyLink,
    LoginToken,
    SignupIntent,
    User,
    UserRole,
)

DELETED_NAME = "Deleted user"


def deleted_email(user_id: UUID) -> str:
    return f"deleted-{user_id}@deleted.invalid"


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        return {}
    sessions = await db.scalars(select(AuthSession).where(AuthSession.user_id == user_id))
    roles = await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))
    links = await db.scalars(select(FamilyLink).where(FamilyLink.user_id == user_id))
    return {
        "profile": {
            "email": user.email,
            "display_name": user.display_name,
            "language": user.language,
            "time_zone": user.time_zone,
            "created_at": user.created_at.isoformat(),
            "email_verified_at": user.email_verified_at.isoformat()
            if user.email_verified_at
            else None,
            "privacy_accepted_at": user.privacy_accepted_at.isoformat(),
            "preferences": user.preferences,
        },
        "sessions": [
            {
                "created_at": s.created_at.isoformat(),
                "last_used_at": s.last_used_at.isoformat(),
                "user_agent": s.user_agent,
                "revoked": s.revoked_at is not None,
            }
            for s in sessions
        ],
        "global_roles": list(roles),
        "family_links": [{"player_id": str(link.player_id)} for link in links],
    }


def eraser(clock: Clock) -> privacy.Eraser:
    async def erase(db: AsyncSession, user_id: UUID) -> None:
        user = await db.get(User, user_id)
        if user is None:
            return
        await db.execute(delete(SignupIntent).where(SignupIntent.email == user.email))
        for model in (AuthSession, LoginToken, UserRole, FamilyLink):
            await db.execute(delete(model).where(model.user_id == user_id))
        await db.execute(
            update(FamilyLink).where(FamilyLink.created_by == user_id).values(created_by=None)
        )
        now = clock.now()
        user.email = deleted_email(user_id)
        user.display_name = DELETED_NAME
        user.email_verified_at = None
        user.preferences = {}
        user.deleted_at = now
        user.updated_at = now

    return erase


def register(clock: Clock) -> None:
    privacy.register("accounts", exporter=export, eraser=eraser(clock), last=True)
