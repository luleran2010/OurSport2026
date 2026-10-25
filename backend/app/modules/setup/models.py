"""Setup tables (docs/03-data-model.md, setup). Draws and schedule plans arrive in T-025."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

SESSION_STATUSES = (
    "intake",
    "extracting",
    "needs_answers",
    "drawing",
    "ready",
    "published",
    "failed",
)
FILE_KINDS = ("rulebook", "team_list", "history", "venue", "other")
DRAFT_STATUSES = ("draft", "ready", "published", "superseded")
_TZ = DateTime(timezone=True)


class SetupSession(Base):
    __tablename__ = "setup_sessions"
    __table_args__ = (CheckConstraint(one_of("status", SESSION_STATUSES), name="status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(15))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    organiser_language: Mapped[str] = mapped_column(String(2), default="en")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
    updated_at: Mapped[datetime] = mapped_column(_TZ)


class IntakeFile(Base):
    __tablename__ = "intake_files"
    __table_args__ = (CheckConstraint(one_of("kind", FILE_KINDS), name="kind"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    setup_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("setup_sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    file_url: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(500))
    filename: Mapped[str | None] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    text_extracted: Mapped[str] = mapped_column(Text)  # redacted
    rows: Mapped[list[list[str]] | None] = mapped_column(JSONB)  # redacted table cells
    # Photos are kept until object storage holds intake files (retention: archive + 1 year).
    image: Mapped[bytes | None] = mapped_column(LargeBinary)
    redaction_report: Mapped[dict[str, int]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_TZ)


class SetupDraft(Base):
    __tablename__ = "setup_drafts"
    __table_args__ = (CheckConstraint(one_of("status", DRAFT_STATUSES), name="status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    setup_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("setup_sessions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    assumptions: Mapped[list[Any]] = mapped_column(JSONB)
    open_questions: Mapped[list[Any]] = mapped_column(JSONB)
    decisions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(_TZ)


DRAW_STATUSES = ("proposed", "published", "discarded")
PLAN_STATUSES = ("proposed", "published", "superseded")
PLAN_REASONS = ("initial", "regenerate", "delay", "withdrawal", "manual")


class DrawRecord(Base):
    """Every draw is kept for audit and can be reproduced from its seed."""

    __tablename__ = "draws"
    __table_args__ = (CheckConstraint(one_of("status", DRAW_STATUSES), name="status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    setup_draft_id: Mapped[UUID] = mapped_column(ForeignKey("setup_drafts.id", ondelete="CASCADE"))
    seed: Mapped[bytes] = mapped_column(LargeBinary)
    pots: Mapped[list[Any]] = mapped_column(JSONB)
    constraints: Mapped[list[Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10))
    revealed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # live draw
    created_at: Mapped[datetime] = mapped_column(_TZ)


class SchedulePlanRecord(Base):
    __tablename__ = "schedule_plans"
    __table_args__ = (
        CheckConstraint(one_of("status", PLAN_STATUSES), name="status"),
        CheckConstraint(one_of("reason", PLAN_REASONS), name="reason"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    based_on_draw_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("draws.id", ondelete="SET NULL")
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    quality: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(_TZ)
