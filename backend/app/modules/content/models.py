"""Content tables (docs/03-data-model.md, content): AI stories and announcement drafts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

_TZ = DateTime(timezone=True)
STORY_KINDS = ("preview", "report", "summary", "news", "team_recap")
STORY_STATUSES = ("draft", "in_review", "published", "blocked", "unpublished")
ANNOUNCEMENT_KINDS = ("result", "schedule_change", "next_up", "custom")
ANNOUNCEMENT_STATUSES = ("draft", "sent", "dismissed")


class Story(Base):
    """One story in one language. Rewrites keep the row and bump `version`."""

    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint(one_of("kind", STORY_KINDS), name="kind"),
        CheckConstraint(one_of("status", STORY_STATUSES), name="status"),
        CheckConstraint(one_of("author_type", ("ai", "human")), name="author_type"),
        Index(
            "uq_stories_subject_kind_language",
            "subject_type",
            "subject_id",
            "kind",
            "language",
            unique=True,
        ),
        Index("ix_stories_tournament_published", "tournament_id", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))
    subject_type: Mapped[str] = mapped_column(String(12))
    subject_id: Mapped[UUID] = mapped_column()
    language: Mapped[str] = mapped_column(String(2))
    headline: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    sentences: Mapped[list[Any]] = mapped_column(JSONB)  # [{text, facts}] for "Why?"
    fact_sheet_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fact_sheets.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(12))
    check_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    author_type: Mapped[str] = mapped_column(String(5))
    author_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    model: Mapped[str | None] = mapped_column(String(60))
    template: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(_TZ)
    version: Mapped[int] = mapped_column(Integer, default=1)
    corrected_at: Mapped[datetime | None] = mapped_column(_TZ)
    review_reason: Mapped[str | None] = mapped_column(String(16))  # blocked_claim, sensitive
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(_TZ)
    removal_reason: Mapped[str | None] = mapped_column(Text)  # statement of reasons
    created_at: Mapped[datetime] = mapped_column(_TZ)
    updated_at: Mapped[datetime] = mapped_column(_TZ)


class StoryVersion(Base):
    """The text of a story before each rewrite or edit."""

    __tablename__ = "story_versions"

    story_id: Mapped[UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    headline: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class Announcement(Base):
    """An organiser announcement in every tournament language; drafts wait for one tap."""

    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(one_of("kind", ANNOUNCEMENT_KINDS), name="kind"),
        CheckConstraint(one_of("status", ANNOUNCEMENT_STATUSES), name="status"),
        Index("ix_announcements_tournament_created", "tournament_id", "created_at"),
        Index("uq_announcements_kind_ref", "tournament_id", "kind", "ref", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str | None] = mapped_column(String(64))  # match id, plan id, …
    texts: Mapped[dict[str, Any]] = mapped_column(JSONB)  # language -> text
    source: Mapped[dict[str, Any]] = mapped_column(JSONB)  # fact sheet, check result
    author_type: Mapped[str] = mapped_column(String(8))  # "ai", "template", "human"
    status: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
    sent_at: Mapped[datetime | None] = mapped_column(_TZ)


class CommentaryItem(Base):
    """One live commentary line in every tournament language (AI or template)."""

    __tablename__ = "commentary_items"
    __table_args__ = (
        CheckConstraint(one_of("author_type", ("ai", "template")), name="author_type"),
        Index("ix_commentary_items_match_created", "match_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # the last event this line covers
    kind: Mapped[str] = mapped_column(String(10))  # "moment"
    moments: Mapped[list[Any]] = mapped_column(JSONB)
    texts: Mapped[dict[str, Any]] = mapped_column(JSONB)  # language -> {text, facts}
    fact_sheet_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fact_sheets.id", ondelete="SET NULL")
    )
    check_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    author_type: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(String(20))  # why a template was used
    created_at: Mapped[datetime] = mapped_column(_TZ)
