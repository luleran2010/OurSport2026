"""lots draws

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-24 20:00:00+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lots_draws",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("drawn_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["drawn_by"],
            ["users.id"],
            name=op.f("fk_lots_draws_drawn_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_lots_draws_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_lots_draws_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lots_draws")),
    )
    op.create_index(
        op.f("ix_lots_draws_tournament_id"), "lots_draws", ["tournament_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lots_draws_tournament_id"), table_name="lots_draws")
    op.drop_table("lots_draws")
