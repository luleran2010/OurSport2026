"""Editorial tables: who is working on which review item, and reported corrections."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

_TZ = DateTime(timezone=True)
CORRECTION_STATUSES = ("open", "fixed", "rejected")
REPORT_KINDS = ("mistake", "privacy", "illegal", "other")


class ReviewClaim(Base):
    """An editor has taken a story in review (one editor per story)."""

    __tablename__ = "review_claims"

    story_id: Mapped[UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    editor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    claimed_at: Mapped[datetime] = mapped_column(_TZ)


class Correction(Base):
    """A reader's report that a published story is wrong (notice and action)."""

    __tablename__ = "corrections"
    __table_args__ = (
        CheckConstraint(one_of("status", CORRECTION_STATUSES), name="status"),
        CheckConstraint(one_of("kind", REPORT_KINDS), name="kind"),
        Index("ix_corrections_status_created", "status", "created_at"),
        Index("ix_corrections_reported_by", "reported_by"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    reported_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10), server_default="mistake")
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
    resolved_at: Mapped[datetime | None] = mapped_column(_TZ)
