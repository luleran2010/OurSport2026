"""Accounts tables (docs/03-data-model.md, accounts). No passwords: magic links only."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

LANGUAGES = ("fi", "en", "bn")
TOKEN_PURPOSES = ("login", "verify")
GLOBAL_ROLES = ("editor", "platform_admin")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(one_of("language", LANGUAGES), name="language"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(2))
    time_zone: Mapped[str] = mapped_column(String(64))
    birth_year_confirmed_13_plus: Mapped[bool] = mapped_column(Boolean)
    privacy_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # tombstone
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class LoginToken(Base):
    __tablename__ = "login_tokens"
    __table_args__ = (CheckConstraint(one_of("purpose", TOKEN_PURPOSES), name="purpose"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignupIntent(Base):
    __tablename__ = "signup_intents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(CITEXT, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(2))
    time_zone: Mapped[str] = mapped_column(String(64))
    follow_target: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    login_token_id: Mapped[UUID] = mapped_column(
        ForeignKey("login_tokens.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthSession(Base):
    """One signed-in device; its refresh token rotates on every use."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_id_revoked_at", "user_id", "revoked_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    refresh_token_hash: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint(one_of("role", GLOBAL_ROLES), name="role"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), primary_key=True)


class FamilyLink(Base):
    """A parent or guardian account linked to a junior player (sees `family_only` data)."""

    __tablename__ = "family_links"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
