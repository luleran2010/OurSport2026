"""rules

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 05:04:26.380791+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rule_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'superseded')", name=op.f("ck_rule_configs_status")
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
            name=op.f("fk_rule_configs_confirmed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_rule_configs_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_configs")),
    )
    op.create_index(
        op.f("ix_rule_configs_tournament_id"), "rule_configs", ["tournament_id"], unique=False
    )
    op.create_table(
        "rulebooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("intake_file_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_rulebooks_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_rulebooks_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rulebooks")),
    )
    op.create_index(
        op.f("ix_rulebooks_tournament_id"), "rulebooks", ["tournament_id"], unique=False
    )
    op.create_table(
        "rule_tests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_config_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=15), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("organiser_verdict", sa.String(length=10), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('worked_example', 'edge_case', 'golden')", name=op.f("ck_rule_tests_kind")
        ),
        sa.CheckConstraint(
            "organiser_verdict IS NULL OR organiser_verdict IN ('correct', 'incorrect')",
            name=op.f("ck_rule_tests_verdict"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_config_id"],
            ["rule_configs.id"],
            name=op.f("fk_rule_tests_rule_config_id_rule_configs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_tests")),
    )
    op.create_index(
        op.f("ix_rule_tests_rule_config_id"), "rule_tests", ["rule_config_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rule_tests_rule_config_id"), table_name="rule_tests")
    op.drop_table("rule_tests")
    op.drop_index(op.f("ix_rulebooks_tournament_id"), table_name="rulebooks")
    op.drop_table("rulebooks")
    op.drop_index(op.f("ix_rule_configs_tournament_id"), table_name="rule_configs")
    op.drop_table("rule_configs")
