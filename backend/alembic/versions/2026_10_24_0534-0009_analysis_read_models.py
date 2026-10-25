"""analysis read models

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24 05:34:03.470756+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_versions",
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("live_seq", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_analysis_versions_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", name=op.f("pk_analysis_versions")),
    )
    op.create_table(
        "bracket_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("bracket", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_bracket_snapshots_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bracket_snapshots")),
    )
    op.create_index(
        "ix_bracket_snapshots_tournament_id_version",
        "bracket_snapshots",
        ["tournament_id", "version"],
        unique=False,
    )
    op.create_table(
        "final_placements",
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("placement", sa.Integer(), nullable=False),
        sa.Column("stage_reached", sa.String(length=15), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_final_placements_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_final_placements_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", "team_id", name=op.f("pk_final_placements")),
    )
    op.create_table(
        "relevance_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_relevance_snapshots_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_relevance_snapshots_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relevance_snapshots")),
    )
    op.create_index(
        op.f("ix_relevance_snapshots_team_id"), "relevance_snapshots", ["team_id"], unique=False
    )
    op.create_index(
        "ix_relevance_snapshots_tournament_id_version",
        "relevance_snapshots",
        ["tournament_id", "version"],
        unique=False,
    )
    op.create_table(
        "scenario_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scenario", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_scenario_snapshots_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_scenario_snapshots_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_snapshots")),
    )
    op.create_index(
        op.f("ix_scenario_snapshots_team_id"), "scenario_snapshots", ["team_id"], unique=False
    )
    op.create_index(
        "ix_scenario_snapshots_tournament_id_version",
        "scenario_snapshots",
        ["tournament_id", "version"],
        unique=False,
    )
    op.create_table(
        "team_journeys",
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("journey", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_journeys_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_team_journeys_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", "team_id", name=op.f("pk_team_journeys")),
    )
    op.create_table(
        "standings_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_standings_snapshots_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_standings_snapshots_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standings_snapshots")),
    )
    op.create_index(
        "ix_standings_snapshots_tournament_id_version",
        "standings_snapshots",
        ["tournament_id", "version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_standings_snapshots_tournament_id_version", table_name="standings_snapshots")
    op.drop_table("standings_snapshots")
    op.drop_table("team_journeys")
    op.drop_index("ix_scenario_snapshots_tournament_id_version", table_name="scenario_snapshots")
    op.drop_index(op.f("ix_scenario_snapshots_team_id"), table_name="scenario_snapshots")
    op.drop_table("scenario_snapshots")
    op.drop_index("ix_relevance_snapshots_tournament_id_version", table_name="relevance_snapshots")
    op.drop_index(op.f("ix_relevance_snapshots_team_id"), table_name="relevance_snapshots")
    op.drop_table("relevance_snapshots")
    op.drop_table("final_placements")
    op.drop_index("ix_bracket_snapshots_tournament_id_version", table_name="bracket_snapshots")
    op.drop_table("bracket_snapshots")
    op.drop_table("analysis_versions")
