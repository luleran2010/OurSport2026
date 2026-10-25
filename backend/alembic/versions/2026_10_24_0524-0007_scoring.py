"""scoring

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24 05:24:40.060282+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_state",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_live_state_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("match_id", name=op.f("pk_live_state")),
    )
    op.create_table(
        "scorer_passes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("pitch_id", sa.Uuid(), nullable=True),
        sa.Column("match_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_scorer_passes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_scorer_passes_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pitch_id"],
            ["pitches.id"],
            name=op.f("fk_scorer_passes_pitch_id_pitches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_scorer_passes_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scorer_passes")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_scorer_passes_token_hash")),
    )
    op.create_index(
        op.f("ix_scorer_passes_tournament_id"), "scorer_passes", ["tournament_id"], unique=False
    )
    op.create_table(
        "match_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("client_seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("period", sa.Integer(), nullable=True),
        sa.Column("clock", sa.String(length=10), nullable=True),
        sa.Column("entered_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("entered_by_pass_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undoes_seq", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entered_by_pass_id"],
            ["scorer_passes.id"],
            name=op.f("fk_match_events_entered_by_pass_id_scorer_passes"),
        ),
        sa.ForeignKeyConstraint(
            ["entered_by_user_id"],
            ["users.id"],
            name=op.f("fk_match_events_entered_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_match_events_match_id_matches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_match_events_player_id_players")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_match_events_team_id_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_events")),
        sa.UniqueConstraint(
            "match_id", "client_seq", name=op.f("uq_match_events_match_id_client_seq")
        ),
        sa.UniqueConstraint("match_id", "seq", name=op.f("uq_match_events_match_id_seq")),
    )


def downgrade() -> None:
    op.drop_table("match_events")
    op.drop_index(op.f("ix_scorer_passes_tournament_id"), table_name="scorer_passes")
    op.drop_table("scorer_passes")
    op.drop_table("live_state")
