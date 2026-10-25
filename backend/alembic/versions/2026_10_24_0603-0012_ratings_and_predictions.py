"""ratings and predictions

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24 06:03:37.922527+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ratings",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("sport", sa.String(length=20), nullable=False),
        sa.Column("age_group", sa.String(length=10), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("prior_source", sa.String(length=10), nullable=False),
        sa.Column("last_tournament_id", sa.Uuid(), nullable=True),
        sa.Column("updated_after_match_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_ratings_team_id_teams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_id", "sport", "age_group", name=op.f("pk_ratings")),
    )
    op.create_table(
        "predictions",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("home_win_low", sa.Float(), nullable=False),
        sa.Column("home_win_high", sa.Float(), nullable=False),
        sa.Column("draw_low", sa.Float(), nullable=True),
        sa.Column("draw_high", sa.Float(), nullable=True),
        sa.Column("away_win_low", sa.Float(), nullable=False),
        sa.Column("away_win_high", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_predictions_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("match_id", name=op.f("pk_predictions")),
    )
    op.create_table(
        "rating_history",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("before", sa.Float(), nullable=False),
        sa.Column("after", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name=op.f("fk_rating_history_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_rating_history_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "match_id", name=op.f("pk_rating_history")),
    )


def downgrade() -> None:
    op.drop_table("rating_history")
    op.drop_table("predictions")
    op.drop_table("ratings")
