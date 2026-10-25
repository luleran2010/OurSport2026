"""Rules tables (docs/03-data-model.md, rules)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

STATUSES = ("draft", "confirmed", "superseded")
TEST_KINDS = ("worked_example", "edge_case", "golden")
VERDICTS = ("correct", "incorrect")
_TZ = DateTime(timezone=True)


class Rulebook(Base):
    __tablename__ = "rulebooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    intake_file_id: Mapped[UUID | None] = mapped_column()
    source_url: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)  # redacted
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class RuleConfigRecord(Base):
    __tablename__ = "rule_configs"
    __table_args__ = (CheckConstraint(one_of("status", STATUSES), name="status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)  # 0 while a draft; 1, 2, … once confirmed
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))
    confirmed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(_TZ)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_TZ)


class RuleTest(Base):
    __tablename__ = "rule_tests"
    __table_args__ = (
        CheckConstraint(one_of("kind", TEST_KINDS), name="kind"),
        CheckConstraint(
            f"organiser_verdict IS NULL OR {one_of('organiser_verdict', VERDICTS)}",
            name="verdict",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    rule_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_configs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(15))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB)
    organiser_verdict: Mapped[str | None] = mapped_column(String(10))
    passed: Mapped[bool] = mapped_column(Boolean)
