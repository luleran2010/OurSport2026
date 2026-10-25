"""competitions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 23:42:03.784618+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("town", sa.String(length=80), nullable=True),
        sa.Column("sports", postgresql.ARRAY(sa.String(length=20)), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("colors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sponsors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('club', 'association', 'school', 'community')",
            name=op.f("ck_organisations_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organisations_slug")),
    )
    op.create_table(
        "sports",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("event_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_sports")),
    )
    op.create_table(
        "venues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("town", sa.String(length=80), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venues")),
    )
    op.create_table(
        "pitches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("is_main", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["venue_id"], ["venues.id"], name=op.f("fk_pitches_venue_id_venues"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pitches")),
    )
    op.create_index(op.f("ix_pitches_venue_id"), "pitches", ["venue_id"], unique=False)
    op.create_table(
        "processing_agreements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("accepted_by", sa.Uuid(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name=op.f("fk_processing_agreements_accepted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_processing_agreements_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_agreements")),
    )
    op.create_index(
        op.f("ix_processing_agreements_organisation_id"),
        "processing_agreements",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("short_name", sa.String(length=20), nullable=True),
        sa.Column("age_group", sa.String(length=10), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "age_group IN ('adult', 'u19', 'u18', 'u17', 'u16', 'u15', 'u14', 'u13', 'u12', 'u11', 'u10', 'u9')",
            name=op.f("ck_teams_age_group"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_teams_organisation_id_organisations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
    )
    op.create_index(op.f("ix_teams_organisation_id"), "teams", ["organisation_id"], unique=False)
    op.create_table(
        "tournament_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("sport", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_tournament_series_organisation_id_organisations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sport"], ["sports.code"], name=op.f("fk_tournament_series_sport_sports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_series")),
        sa.UniqueConstraint("slug", name=op.f("uq_tournament_series_slug")),
    )
    op.create_index(
        op.f("ix_tournament_series_organisation_id"),
        "tournament_series",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("shirt_number", sa.Integer(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("visibility", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('public', 'family_only', 'hidden')", name=op.f("ck_players_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_players_team_id_teams"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_players")),
    )
    op.create_index(op.f("ix_players_team_id"), "players", ["team_id"], unique=False)
    op.create_table(
        "team_aliases",
        sa.Column("alias_normalised", sa.String(length=160), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('setup', 'organiser', 'import')", name=op.f("ck_team_aliases_source")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_aliases_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias_normalised", "team_id", name=op.f("pk_team_aliases")),
    )
    op.create_index(op.f("ix_team_aliases_team_id"), "team_aliases", ["team_id"], unique=False)
    op.create_table(
        "tournaments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=True),
        sa.Column("edition_label", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("sport", sa.String(length=20), nullable=False),
        sa.Column("season", sa.String(length=20), nullable=True),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("age_group", sa.String(length=10), nullable=False),
        sa.Column("is_junior", sa.Boolean(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_config_id", sa.Uuid(), nullable=True),
        sa.Column("format_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("policy_catalogue_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "age_group IN ('adult', 'u19', 'u18', 'u17', 'u16', 'u15', 'u14', 'u13', 'u12', 'u11', 'u10', 'u9')",
            name=op.f("ck_tournaments_age_group"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'upcoming', 'active', 'finished', 'archived')",
            name=op.f("ck_tournaments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_tournaments_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["tournament_series.id"],
            name=op.f("fk_tournaments_series_id_tournament_series"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sport"], ["sports.code"], name=op.f("fk_tournaments_sport_sports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournaments")),
        sa.UniqueConstraint("slug", name=op.f("uq_tournaments_slug")),
    )
    op.create_index(
        "ix_tournaments_organisation_id_starts_on",
        "tournaments",
        ["organisation_id", "starts_on"],
        unique=False,
    )
    op.create_index(op.f("ix_tournaments_series_id"), "tournaments", ["series_id"], unique=False)
    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("guardian_user_id", sa.Uuid(), nullable=True),
        sa.Column("guardian_contact", sa.String(length=254), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('profile', 'stats', 'filming')", name=op.f("ck_consents_scope")
        ),
        sa.ForeignKeyConstraint(
            ["guardian_user_id"],
            ["users.id"],
            name=op.f("fk_consents_guardian_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_consents_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_player_id"), "consents", ["player_id"], unique=False)
    op.create_table(
        "family_links",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_family_links_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_family_links_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_family_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "player_id", name=op.f("pk_family_links")),
    )
    op.create_index(op.f("ix_family_links_player_id"), "family_links", ["player_id"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_groups_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("tournament_id", "name", name=op.f("uq_groups_tournament_id_name")),
    )
    op.create_table(
        "tournament_staff",
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'organiser', 'scorer')", name=op.f("ck_tournament_staff_role")
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_staff_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tournament_staff_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", "user_id", name=op.f("pk_tournament_staff")),
    )
    op.create_index(
        op.f("ix_tournament_staff_user_id"), "tournament_staff", ["user_id"], unique=False
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=15), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("home_team_id", sa.Uuid(), nullable=True),
        sa.Column("away_team_id", sa.Uuid(), nullable=True),
        sa.Column("home_source", sa.String(length=40), nullable=True),
        sa.Column("away_source", sa.String(length=40), nullable=True),
        sa.Column("venue_id", sa.Uuid(), nullable=True),
        sa.Column("pitch_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("data_level", sa.String(length=10), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "data_level IN ('results', 'events')", name=op.f("ck_matches_data_level")
        ),
        sa.CheckConstraint(
            "stage IN ('group', 'round_of_16', 'quarter_final', 'semi_final', 'third_place', 'final')",
            name=op.f("ck_matches_stage"),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'live', 'finished', 'postponed', 'cancelled', 'walkover')",
            name=op.f("ck_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"], ["teams.id"], name=op.f("fk_matches_away_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_matches_group_id_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"], ["teams.id"], name=op.f("fk_matches_home_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["pitch_id"], ["pitches.id"], name=op.f("fk_matches_pitch_id_pitches")
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_matches_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"], ["venues.id"], name=op.f("fk_matches_venue_id_venues")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matches")),
        sa.UniqueConstraint("tournament_id", "code", name=op.f("uq_matches_tournament_id_code")),
    )
    op.create_index(op.f("ix_matches_away_team_id"), "matches", ["away_team_id"], unique=False)
    op.create_index(op.f("ix_matches_home_team_id"), "matches", ["home_team_id"], unique=False)
    op.create_index(
        "ix_matches_pitch_id_starts_at", "matches", ["pitch_id", "starts_at"], unique=False
    )
    op.create_index(
        "ix_matches_tournament_id_starts_at",
        "matches",
        ["tournament_id", "starts_at"],
        unique=False,
    )
    op.create_table(
        "tournament_teams",
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("pot", sa.Integer(), nullable=True),
        sa.Column("seeding_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_tournament_teams_group_id_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_tournament_teams_team_id_teams"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_teams_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", "team_id", name=op.f("pk_tournament_teams")),
    )
    op.create_index(
        op.f("ix_tournament_teams_group_id"), "tournament_teams", ["group_id"], unique=False
    )
    op.create_index(
        op.f("ix_tournament_teams_team_id"), "tournament_teams", ["team_id"], unique=False
    )

    sports = sa.table(
        "sports",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("event_types", postgresql.JSONB),
    )
    op.bulk_insert(
        sports,
        [
            {
                "code": "football",
                "name": "Football",
                "event_types": [
                    "goal",
                    "own_goal",
                    "penalty_goal",
                    "penalty_miss",
                    "yellow",
                    "second_yellow",
                    "red",
                    "substitution",
                    "period_start",
                    "period_end",
                    "shootout_kick",
                ],
            },
            {
                "code": "ice_hockey",
                "name": "Ice hockey",
                "event_types": ["goal", "penalty", "period_start", "period_end", "shootout_shot"],
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tournament_teams_team_id"), table_name="tournament_teams")
    op.drop_index(op.f("ix_tournament_teams_group_id"), table_name="tournament_teams")
    op.drop_table("tournament_teams")
    op.drop_index("ix_matches_tournament_id_starts_at", table_name="matches")
    op.drop_index("ix_matches_pitch_id_starts_at", table_name="matches")
    op.drop_index(op.f("ix_matches_home_team_id"), table_name="matches")
    op.drop_index(op.f("ix_matches_away_team_id"), table_name="matches")
    op.drop_table("matches")
    op.drop_index(op.f("ix_tournament_staff_user_id"), table_name="tournament_staff")
    op.drop_table("tournament_staff")
    op.drop_table("groups")
    op.drop_index(op.f("ix_family_links_player_id"), table_name="family_links")
    op.drop_table("family_links")
    op.drop_index(op.f("ix_consents_player_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index(op.f("ix_tournaments_series_id"), table_name="tournaments")
    op.drop_index("ix_tournaments_organisation_id_starts_on", table_name="tournaments")
    op.drop_table("tournaments")
    op.drop_index(op.f("ix_team_aliases_team_id"), table_name="team_aliases")
    op.drop_table("team_aliases")
    op.drop_index(op.f("ix_players_team_id"), table_name="players")
    op.drop_table("players")
    op.drop_index(op.f("ix_tournament_series_organisation_id"), table_name="tournament_series")
    op.drop_table("tournament_series")
    op.drop_index(op.f("ix_teams_organisation_id"), table_name="teams")
    op.drop_table("teams")
    op.drop_index(
        op.f("ix_processing_agreements_organisation_id"), table_name="processing_agreements"
    )
    op.drop_table("processing_agreements")
    op.drop_index(op.f("ix_pitches_venue_id"), table_name="pitches")
    op.drop_table("pitches")
    op.drop_table("venues")
    op.drop_table("sports")
    op.drop_table("organisations")
