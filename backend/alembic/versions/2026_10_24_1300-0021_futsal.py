"""futsal

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-24 13:00:00+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES = [
    "foul",
    "goal",
    "penalty_missed",
    "period_end",
    "period_start",
    "red_card",
    "second_yellow",
    "shootout_kick",
    "substitution",
    "timeout",
    "undo",
    "yellow_card",
]


def upgrade() -> None:
    sports = sa.table(
        "sports",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("event_types", postgresql.JSONB),
    )
    op.bulk_insert(sports, [{"code": "futsal", "name": "Futsal", "event_types": EVENT_TYPES}])


def downgrade() -> None:
    op.execute("DELETE FROM sports WHERE code = 'futsal'")
