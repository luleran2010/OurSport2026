"""Analysis read models (docs/03-data-model.md, analysis). Fan reads only these tables.

Each snapshot is versioned; the latest version is served. `source_version` is a hash of
everything the computation read, so an unchanged tournament is never recomputed.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

_TZ = DateTime(timezone=True)


class StandingsSnapshot(Base):
    __tablename__ = "standings_snapshots"
    __table_args__ = (
        Index("ix_standings_snapshots_tournament_id_version", "tournament_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    source_version: Mapped[str] = mapped_column(String(64))
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)  # "if it ended now"
    rows: Mapped[list[Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class ScenarioSnapshot(Base):
    __tablename__ = "scenario_snapshots"
    __table_args__ = (
        Index("ix_scenario_snapshots_tournament_id_version", "tournament_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    scenario: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class BracketSnapshot(Base):
    __tablename__ = "bracket_snapshots"
    __table_args__ = (
        Index("ix_bracket_snapshots_tournament_id_version", "tournament_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    bracket: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class RelevanceSnapshot(Base):
    __tablename__ = "relevance_snapshots"
    __table_args__ = (
        Index("ix_relevance_snapshots_tournament_id_version", "tournament_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    items: Mapped[list[Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class TeamJourney(Base):
    __tablename__ = "team_journeys"

    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    journey: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class FinalPlacement(Base):
    __tablename__ = "final_placements"

    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    placement: Mapped[int] = mapped_column(Integer)
    stage_reached: Mapped[str] = mapped_column(String(15))
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class AnalysisVersion(Base):
    """The last computed version per tournament, for coalescing recalculations."""

    __tablename__ = "analysis_versions"

    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    source_version: Mapped[str] = mapped_column(String(64))
    live_seq: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)  # match id -> seq
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class Rating(Base):
    __tablename__ = "ratings"

    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    sport: Mapped[str] = mapped_column(String(20), primary_key=True)
    age_group: Mapped[str] = mapped_column(String(10), primary_key=True)
    rating: Mapped[float] = mapped_column(Float)
    games: Mapped[int] = mapped_column(Integer)
    prior_source: Mapped[str] = mapped_column(String(10))
    last_tournament_id: Mapped[UUID | None] = mapped_column()  # carry-over between editions
    updated_after_match_id: Mapped[UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(_TZ)


class RatingHistory(Base):
    __tablename__ = "rating_history"

    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    before: Mapped[float] = mapped_column(Float)
    after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(_TZ)


class PredictionRecord(Base):
    __tablename__ = "predictions"

    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    home_win_low: Mapped[float] = mapped_column(Float)
    home_win_high: Mapped[float] = mapped_column(Float)
    draw_low: Mapped[float | None] = mapped_column(Float)
    draw_high: Mapped[float | None] = mapped_column(Float)
    away_win_low: Mapped[float] = mapped_column(Float)
    away_win_high: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(10))
    factors: Mapped[list[Any]] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class TeamComparison(Base):
    __tablename__ = "team_comparisons"

    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class MatchAnalysis(Base):
    __tablename__ = "match_analyses"

    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(_TZ)


class FactSheet(Base):
    """Verified facts a writing task may use (docs/07, Fact sheets). One row per distinct
    input: `inputs_hash` covers the facts, the context and the builder version."""

    __tablename__ = "fact_sheets"
    __table_args__ = (
        Index("ix_fact_sheets_subject", "subject_type", "subject_id", "kind"),
        Index("uq_fact_sheets_inputs_hash", "inputs_hash", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    subject_type: Mapped[str] = mapped_column(String(12))
    subject_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    facts: Mapped[list[Any]] = mapped_column(JSONB)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(_TZ)
