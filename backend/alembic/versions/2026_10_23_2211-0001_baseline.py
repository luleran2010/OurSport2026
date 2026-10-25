"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-10-23 22:11:33.720949+00:00

Empty starting point: gives every database an `alembic_version` row so readiness can
verify migrations are at head before any module owns a table.
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
