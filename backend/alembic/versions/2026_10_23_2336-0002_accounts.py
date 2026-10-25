"""accounts

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 23:36:15.978781+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("birth_year_confirmed_13_plus", sa.Boolean(), nullable=False),
        sa.Column("privacy_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("language IN ('fi', 'en', 'bn')", name=op.f("ck_users_language")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "login_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('login', 'verify')", name=op.f("ck_login_tokens_purpose")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_login_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_login_tokens_token_hash")),
    )
    op.create_index(op.f("ix_login_tokens_user_id"), "login_tokens", ["user_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )
    op.create_index(
        "ix_sessions_user_id_revoked_at", "sessions", ["user_id", "revoked_at"], unique=False
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.CheckConstraint("role IN ('editor', 'platform_admin')", name=op.f("ck_user_roles_role")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "role", name=op.f("pk_user_roles")),
    )
    op.create_table(
        "signup_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("follow_target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("login_token_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["login_token_id"],
            ["login_tokens.id"],
            name=op.f("fk_signup_intents_login_token_id_login_tokens"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signup_intents")),
        sa.UniqueConstraint("login_token_id", name=op.f("uq_signup_intents_login_token_id")),
    )
    op.create_index(op.f("ix_signup_intents_email"), "signup_intents", ["email"], unique=False)
    op.create_index(
        op.f("ix_signup_intents_expires_at"), "signup_intents", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_signup_intents_expires_at"), table_name="signup_intents")
    op.drop_index(op.f("ix_signup_intents_email"), table_name="signup_intents")
    op.drop_table("signup_intents")
    op.drop_table("user_roles")
    op.drop_index("ix_sessions_user_id_revoked_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_login_tokens_user_id"), table_name="login_tokens")
    op.drop_table("login_tokens")
    op.drop_table("users")
