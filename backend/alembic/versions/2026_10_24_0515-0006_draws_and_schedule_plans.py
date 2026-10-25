"""draws and schedule plans

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24 05:15:17.940560+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "draws",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("setup_draft_id", sa.Uuid(), nullable=False),
        sa.Column("seed", sa.LargeBinary(), nullable=False),
        sa.Column("pots", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'published', 'discarded')", name=op.f("ck_draws_status")
        ),
        sa.ForeignKeyConstraint(
            ["setup_draft_id"],
            ["setup_drafts.id"],
            name=op.f("fk_draws_setup_draft_id_setup_drafts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_draws_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draws")),
    )
    op.create_index(op.f("ix_draws_tournament_id"), "draws", ["tournament_id"], unique=False)
    op.create_table(
        "schedule_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("based_on_draw_id", sa.Uuid(), nullable=True),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reason IN ('initial', 'regenerate', 'delay', 'withdrawal', 'manual')",
            name=op.f("ck_schedule_plans_reason"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'published', 'superseded')",
            name=op.f("ck_schedule_plans_status"),
        ),
        sa.ForeignKeyConstraint(
            ["based_on_draw_id"],
            ["draws.id"],
            name=op.f("fk_schedule_plans_based_on_draw_id_draws"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_schedule_plans_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_plans")),
    )
    op.create_index(
        op.f("ix_schedule_plans_tournament_id"), "schedule_plans", ["tournament_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_schedule_plans_tournament_id"), table_name="schedule_plans")
    op.drop_table("schedule_plans")
    op.drop_index(op.f("ix_draws_tournament_id"), table_name="draws")
    op.drop_table("draws")
