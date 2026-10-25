"""Media tables (docs/03-data-model.md, media): streams someone else produces, the venue
filming notice, offline consent attestations and filming opt-outs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

_TZ = DateTime(timezone=True)
STREAM_STATUSES = ("live", "paused", "ended")
STREAM_PROVIDERS = ("youtube", "mux", "cloudflare", "other")


class Stream(Base):
    """A playback link for a match, attached only after the filming check passed."""

    __tablename__ = "streams"
    __table_args__ = (
        CheckConstraint(one_of("status", STREAM_STATUSES), name="status"),
        CheckConstraint(one_of("provider", STREAM_PROVIDERS), name="provider"),
        Index("ix_streams_match_created", "match_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(12))
    playback_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(8))
    keep_replay: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_check: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the checks that passed
    rights_confirmed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(_TZ)
    ended_at: Mapped[datetime | None] = mapped_column(_TZ)
    created_at: Mapped[datetime] = mapped_column(_TZ)


class FilmingNotice(Base):
    """The notice shown at the venue (and in team emails) that matches are filmed."""

    __tablename__ = "filming_notices"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    texts: Mapped[dict[str, Any]] = mapped_column(JSONB)  # language -> text
    version: Mapped[int] = mapped_column()
    published_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class FilmingAttestation(Base):
    """The organiser attests that filming consents were collected offline (signed forms)."""

    __tablename__ = "filming_attestations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    attested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class FilmingOptOut(Base):
    """Someone asked not to be filmed; blocks streams of the affected matches until the
    organiser resolves it."""

    __tablename__ = "filming_optouts"
    __table_args__ = (Index("ix_filming_optouts_tournament_open", "tournament_id", "resolved_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    player_id: Mapped[UUID | None] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TZ)
    resolved_at: Mapped[datetime | None] = mapped_column(_TZ)
    resolution: Mapped[str | None] = mapped_column(Text)
