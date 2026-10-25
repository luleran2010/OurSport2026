"""follows

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24 05:54:46.515107+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=15), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("notify", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('organisation', 'team', 'tournament', 'series')",
            name=op.f("ck_follows_target_type"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_follows_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follows")),
        sa.UniqueConstraint(
            "user_id",
            "target_type",
            "target_id",
            name=op.f("uq_follows_user_id_target_type_target_id"),
        ),
    )
    op.create_index(
        "ix_follows_target_type_target_id", "follows", ["target_type", "target_id"], unique=False
    )
    op.create_index(
        "uq_follows_primary", "follows", ["user_id"], unique=True, postgresql_where="is_primary"
    )


def downgrade() -> None:
    op.drop_index("uq_follows_primary", table_name="follows", postgresql_where="is_primary")
    op.drop_index("ix_follows_target_type_target_id", table_name="follows")
    op.drop_table("follows")
