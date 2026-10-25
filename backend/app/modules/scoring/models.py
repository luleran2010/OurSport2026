"""Scoring tables (docs/03-data-model.md, scoring). `match_events` is append-only."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

_TZ = DateTime(timezone=True)


class MatchEvent(Base):
    """One thing that happened in a match. Never updated or deleted: undo is a new event."""

    __tablename__ = "match_events"
    __table_args__ = (
        UniqueConstraint("match_id", "seq"),
        UniqueConstraint("match_id", "client_seq"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id", ondelete="RESTRICT"))
    seq: Mapped[int] = mapped_column(BigInteger)
    client_seq: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[UUID | None] = mapped_column(ForeignKey("players.id"))
    period: Mapped[int | None] = mapped_column(Integer)
    clock: Mapped[str | None] = mapped_column(String(10))  # "37:12"
    entered_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    entered_by_pass_id: Mapped[UUID | None] = mapped_column(ForeignKey("scorer_passes.id"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
    undoes_seq: Mapped[int | None] = mapped_column(BigInteger)


class LiveState(Base):
    __tablename__ = "live_state"

    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(_TZ)


class ScorerPass(Base):
    __tablename__ = "scorer_passes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    pitch_id: Mapped[UUID | None] = mapped_column(ForeignKey("pitches.id", ondelete="CASCADE"))
    match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    valid_from: Mapped[datetime] = mapped_column(_TZ)
    valid_until: Mapped[datetime] = mapped_column(_TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(_TZ)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
