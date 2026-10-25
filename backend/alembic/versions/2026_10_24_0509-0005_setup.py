"""setup

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24 05:09:26.481420+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "setup_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=15), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("organiser_language", sa.String(length=2), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('intake', 'extracting', 'needs_answers', 'drawing', 'ready', 'published', 'failed')",
            name=op.f("ck_setup_sessions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_setup_sessions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_setup_sessions_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_setup_sessions")),
    )
    op.create_index(
        op.f("ix_setup_sessions_tournament_id"), "setup_sessions", ["tournament_id"], unique=False
    )
    op.create_table(
        "intake_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("setup_session_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("text_extracted", sa.Text(), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("redaction_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('rulebook', 'team_list', 'history', 'venue', 'other')",
            name=op.f("ck_intake_files_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["setup_session_id"],
            ["setup_sessions.id"],
            name=op.f("fk_intake_files_setup_session_id_setup_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_files")),
    )
    op.create_index(
        op.f("ix_intake_files_setup_session_id"), "intake_files", ["setup_session_id"], unique=False
    )
    op.create_table(
        "setup_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("setup_session_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decisions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'published', 'superseded')",
            name=op.f("ck_setup_drafts_status"),
        ),
        sa.ForeignKeyConstraint(
            ["setup_session_id"],
            ["setup_sessions.id"],
            name=op.f("fk_setup_drafts_setup_session_id_setup_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_setup_drafts")),
    )
    op.create_index(
        op.f("ix_setup_drafts_setup_session_id"), "setup_drafts", ["setup_session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_setup_drafts_setup_session_id"), table_name="setup_drafts")
    op.drop_table("setup_drafts")
    op.drop_index(op.f("ix_intake_files_setup_session_id"), table_name="intake_files")
    op.drop_table("intake_files")
    op.drop_index(op.f("ix_setup_sessions_tournament_id"), table_name="setup_sessions")
    op.drop_table("setup_sessions")
