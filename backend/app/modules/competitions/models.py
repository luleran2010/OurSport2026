"""Competitions tables (docs/03-data-model.md, competitions)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of
from app.core.ids import new_id

ORGANISATION_KINDS = ("club", "association", "school", "community")
TOURNAMENT_STATUSES = ("draft", "upcoming", "active", "finished", "archived")
AGE_GROUPS = ("adult", "u19", "u18", "u17", "u16", "u15", "u14", "u13", "u12", "u11", "u10", "u9")
STAFF_ROLES = ("owner", "organiser", "scorer")
VISIBILITIES = ("public", "family_only", "hidden")
CONSENT_SCOPES = ("profile", "stats", "filming")
ALIAS_SOURCES = ("setup", "organiser", "import")
MATCH_STAGES = (
    "group",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "third_place",
    "final",
)
MATCH_STATUSES = ("scheduled", "live", "finished", "postponed", "cancelled", "walkover")
DATA_LEVELS = ("results", "events")

_TZ = DateTime(timezone=True)


class Sport(Base):
    __tablename__ = "sports"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    event_types: Mapped[list[str]] = mapped_column(JSONB)


class Organisation(Base):
    __tablename__ = "organisations"
    __table_args__ = (CheckConstraint(one_of("kind", ORGANISATION_KINDS), name="kind"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    town: Mapped[str | None] = mapped_column(String(80))
    sports: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    colors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sponsors: Mapped[list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_TZ)


class ProcessingAgreement(Base):
    __tablename__ = "processing_agreements"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    organisation_id: Mapped[UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(20))
    accepted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    accepted_at: Mapped[datetime] = mapped_column(_TZ)


class TournamentSeries(Base):
    __tablename__ = "tournament_series"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    organisation_id: Mapped[UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    sport: Mapped[str] = mapped_column(ForeignKey("sports.code"))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        CheckConstraint(one_of("status", TOURNAMENT_STATUSES), name="status"),
        CheckConstraint(one_of("age_group", AGE_GROUPS), name="age_group"),
        Index("ix_tournaments_organisation_id_starts_on", "organisation_id", "starts_on"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    series_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tournament_series.id", ondelete="RESTRICT"), index=True
    )
    edition_label: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    sport: Mapped[str] = mapped_column(ForeignKey("sports.code"))
    season: Mapped[str | None] = mapped_column(String(20))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    status: Mapped[str] = mapped_column(String(10))
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    time_zone: Mapped[str] = mapped_column(String(64))
    age_group: Mapped[str] = mapped_column(String(10))
    is_junior: Mapped[bool] = mapped_column(Boolean)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rule_config_id: Mapped[UUID | None] = mapped_column()  # FK added with the rules module
    format_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    policy_catalogue_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(_TZ)
    updated_at: Mapped[datetime] = mapped_column(_TZ)


class TournamentStaff(Base):
    __tablename__ = "tournament_staff"
    __table_args__ = (CheckConstraint(one_of("role", STAFF_ROLES), name="role"),)

    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(10))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tournament_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(20))
    order: Mapped[int] = mapped_column(Integer)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (CheckConstraint(one_of("age_group", AGE_GROUPS), name="age_group"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    organisation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str | None] = mapped_column(String(20))
    age_group: Mapped[str] = mapped_column(String(10))
    # Organiser use only: never public, never sent to the LLM (docs/09).
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (CheckConstraint(one_of("source", ALIAS_SOURCES), name="source"),)

    alias_normalised: Mapped[str] = mapped_column(String(160), primary_key=True)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class TournamentTeam(Base):
    __tablename__ = "tournament_teams"

    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), index=True
    )
    seed: Mapped[int | None] = mapped_column(Integer)
    pot: Mapped[int | None] = mapped_column(Integer)
    seeding_reason: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    withdrawn_at: Mapped[datetime | None] = mapped_column(_TZ)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (CheckConstraint(one_of("visibility", VISIBILITIES), name="visibility"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    shirt_number: Mapped[int | None] = mapped_column(Integer)
    birth_year: Mapped[int | None] = mapped_column(Integer)  # never a full birth date
    visibility: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(_TZ)


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (CheckConstraint(one_of("scope", CONSENT_SCOPES), name="scope"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    guardian_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    guardian_contact: Mapped[str] = mapped_column(String(254))
    scope: Mapped[str] = mapped_column(String(10))
    granted_at: Mapped[datetime] = mapped_column(_TZ)
    withdrawn_at: Mapped[datetime | None] = mapped_column(_TZ)


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    town: Mapped[str | None] = mapped_column(String(80))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


class Pitch(Base):
    __tablename__ = "pitches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    venue_id: Mapped[UUID] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    order: Mapped[int] = mapped_column(Integer)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(one_of("stage", MATCH_STAGES), name="stage"),
        CheckConstraint(one_of("status", MATCH_STATUSES), name="status"),
        CheckConstraint(one_of("data_level", DATA_LEVELS), name="data_level"),
        UniqueConstraint("tournament_id", "code"),
        Index("ix_matches_tournament_id_starts_at", "tournament_id", "starts_at"),
        Index("ix_matches_pitch_id_starts_at", "pitch_id", "starts_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    stage: Mapped[str] = mapped_column(String(15))
    code: Mapped[str] = mapped_column(String(10))
    round: Mapped[int | None] = mapped_column(Integer)
    home_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    home_source: Mapped[str | None] = mapped_column(String(40))
    away_source: Mapped[str | None] = mapped_column(String(40))
    venue_id: Mapped[UUID | None] = mapped_column(ForeignKey("venues.id"))
    pitch_id: Mapped[UUID | None] = mapped_column(ForeignKey("pitches.id"))
    starts_at: Mapped[datetime] = mapped_column(_TZ)
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10), default="scheduled")
    data_level: Mapped[str] = mapped_column(String(10), default="events")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)


class LotsDraw(Base):
    """A drawing of lots the organiser held for teams nothing else could separate."""

    __tablename__ = "lots_draws"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tournament_id: Mapped[UUID] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    order: Mapped[list[Any]] = mapped_column(JSONB)  # team ids, as drawn
    drawn_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(_TZ)
