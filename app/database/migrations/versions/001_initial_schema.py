"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ENUMS
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tournament_status_enum AS ENUM (
                'draft','hidden','testing','scheduled',
                'registration_open','registration_closed',
                'checkin_open','checkin_closed','live',
                'under_review','completed','archived','cancelled'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tournament_format_enum AS ENUM (
                'single_elimination','double_elimination','triple_elimination',
                'round_robin','swiss','group_stage','season_league','points_league',
                'battle_royale','free_for_all','race_time_trial'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE team_size_type_enum AS ENUM (
                'solo','duo','trio','squad','team','hybrid'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE event_type_enum AS ENUM (
                'qualifier','finals','multi_stage','scrims','invite_only','open'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE registration_status_enum AS ENUM (
                'pending','auto_approved','manually_approved',
                'rejected','changes_requested','flagged','hold'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE match_status_enum AS ENUM (
                'scheduled','checkin_open','checkin_closed','ready','live',
                'awaiting_score','under_review','protested','verified',
                'completed','voided','rescheduled'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE dispute_status_enum AS ENUM (
                'open','assigned','investigating','waiting_for_response',
                'escalated','resolved','rejected','closed'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE dispute_case_type_enum AS ENUM (
                'wrong_score','cheating_report','rule_violation','disconnect',
                'registration_issue','verification_issue','team_issue','general_support'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE staff_role_enum AS ENUM (
                'owner','super_admin','tournament_admin','tournament_manager',
                'referee','moderator','verifier','helper','support','analyst'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notification_channel_enum AS ENUM (
                'discord_dm','discord_channel','role_ping','dashboard_bell','staff_inbox'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE form_field_type_enum AS ENUM (
                'short_text','long_text','number','dropdown','checkbox',
                'multi_select','yes_no','file_image','roster_entry'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$
    """)

    # organizations
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # guilds
    op.create_table(
        "guilds",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("discord_guild_id", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_guilds_org", "guilds", ["organization_id"])
    op.create_index("idx_guilds_discord_id", "guilds", ["discord_guild_id"])

    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("discord_user_id", sa.String(20), nullable=False, unique=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("discriminator", sa.String(4), nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("global_settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_users_discord_id", "users", ["discord_user_id"])

    # tournaments
    op.create_table(
        "tournaments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("guild_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("game", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("format", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False, server_default="open"),
        sa.Column("team_size_type", sa.String(20), nullable=False, server_default="solo"),
        sa.Column("min_team_size", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_team_size", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_teams", sa.Integer, nullable=True),
        sa.Column("max_players", sa.Integer, nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("platform", sa.String(100), nullable=True),
        sa.Column("prize_pool", sa.String(500), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("registration_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkin_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkin_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rules", sa.Text, nullable=True),
        sa.Column("scoring_rules", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("tiebreaker_rules", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("seeding_method", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("dispute_policy", sa.Text, nullable=True),
        sa.Column("auto_removal_policy", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("reserve_handling", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("allow_duplicates", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("branding", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("channel_config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "slug", name="uq_tournament_slug"),
    )
    op.create_index("idx_tournaments_org", "tournaments", ["organization_id"])
    op.create_index("idx_tournaments_guild", "tournaments", ["guild_id"])
    op.create_index("idx_tournaments_status", "tournaments", ["status"])
    op.create_index("idx_tournaments_created", "tournaments", ["created_at"])

    # staff_members
    op.create_table(
        "staff_members",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=True),
        sa.Column("permissions", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "user_id", "tournament_id", "role", name="uq_staff"),
    )
    op.create_index("idx_staff_org", "staff_members", ["organization_id"])
    op.create_index("idx_staff_tournament", "staff_members", ["tournament_id"])
    op.create_index("idx_staff_user", "staff_members", ["user_id"])

    # registration_forms
    op.create_table(
        "registration_forms",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_reg_forms_tournament", "registration_forms", ["tournament_id"])

    # form_fields
    op.create_table(
        "form_fields",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("form_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("registration_forms.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("field_type", sa.String(30), nullable=False),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_unique", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("options", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("conditional_logic", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("validation_rules", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_form_fields_form", "form_fields", ["form_id"])
    op.create_index("idx_form_fields_tournament", "form_fields", ["tournament_id"])

    # teams
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("tag", sa.String(10), nullable=True),
        sa.Column("captain_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("seed", sa.Integer, nullable=True),
        sa.Column("is_reserve", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("checkin_status", sa.String(30), nullable=False, server_default="not_checked_in"),
        sa.Column("discord_role_id", sa.String(20), nullable=True),
        sa.Column("text_channel_id", sa.String(20), nullable=True),
        sa.Column("voice_channel_id", sa.String(20), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "tournament_id", "name", name="uq_team_name"),
    )
    op.create_index("idx_teams_tournament", "teams", ["tournament_id"])
    op.create_index("idx_teams_org", "teams", ["organization_id"])
    op.create_index("idx_teams_captain", "teams", ["captain_id"])

    # registrations
    op.create_table(
        "registrations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("form_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("duplicate_flags", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_registrations_tournament", "registrations", ["tournament_id"])
    op.create_index("idx_registrations_org", "registrations", ["organization_id"])
    op.create_index("idx_registrations_status", "registrations", ["status"])
    op.create_index("idx_registrations_submitted_by", "registrations", ["submitted_by"])

    # team_members
    op.create_table(
        "team_members",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tournament_id", "team_id", "user_id", name="uq_team_member"),
    )
    op.create_index("idx_team_members_team", "team_members", ["team_id"])
    op.create_index("idx_team_members_tournament", "team_members", ["tournament_id"])
    op.create_index("idx_team_members_user", "team_members", ["user_id"])

    # evidence_files
    op.create_table(
        "evidence_files",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=True),
        sa.Column("registration_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("registrations.id"), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_data", sa.LargeBinary, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_evidence_tournament", "evidence_files", ["tournament_id"])
    op.create_index("idx_evidence_registration", "evidence_files", ["registration_id"])

    # brackets
    op.create_table(
        "brackets",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default="Main Bracket"),
        sa.Column("bracket_type", sa.String(50), nullable=False),
        sa.Column("stage", sa.Integer, nullable=False, server_default="1"),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("bracket_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_brackets_tournament", "brackets", ["tournament_id"])

    # matches
    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("bracket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("brackets.id"), nullable=True),
        sa.Column("round", sa.Integer, nullable=True),
        sa.Column("match_number", sa.Integer, nullable=True),
        sa.Column("lobby_number", sa.Integer, nullable=True),
        sa.Column("team1_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("team2_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("winner_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("loser_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_team1", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("score_team2", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("score_overridden_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("score_override_reason", sa.Text, nullable=True),
        sa.Column("private_channel_id", sa.String(20), nullable=True),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("match_log", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_matches_tournament", "matches", ["tournament_id"])
    op.create_index("idx_matches_bracket", "matches", ["bracket_id"])
    op.create_index("idx_matches_status", "matches", ["status"])
    op.create_index("idx_matches_team1", "matches", ["team1_id"])
    op.create_index("idx_matches_team2", "matches", ["team2_id"])

    # battle_royale_results
    op.create_table(
        "battle_royale_results",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("lobby_number", sa.Integer, nullable=False),
        sa.Column("placement", sa.Integer, nullable=True),
        sa.Column("kill_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("placement_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bonus_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("penalty_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_br_results_tournament", "battle_royale_results", ["tournament_id"])
    op.create_index("idx_br_results_match", "battle_royale_results", ["match_id"])

    # standings
    op.create_table(
        "standings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("bracket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("brackets.id"), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("rank", sa.Integer, nullable=True),
        sa.Column("points", sa.Numeric, nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("draws", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matches_played", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tiebreaker_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "bracket_id", "team_id", name="uq_standings"),
    )
    op.create_index("idx_standings_tournament", "standings", ["tournament_id"])

    # checkins
    op.create_table(
        "checkins",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("method", sa.String(20), nullable=False, server_default="button"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_checkins_tournament", "checkins", ["tournament_id"])
    op.create_index("idx_checkins_match", "checkins", ["match_id"])
    op.create_index("idx_checkins_team", "checkins", ["team_id"])

    # disputes
    op.create_table(
        "disputes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("opened_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("case_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("ai_context", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_id", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_disputes_tournament", "disputes", ["tournament_id"])
    op.create_index("idx_disputes_status", "disputes", ["status"])

    # evidence_files: add dispute_id column
    op.add_column("evidence_files", sa.Column("dispute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("disputes.id"), nullable=True))
    op.create_index("idx_evidence_dispute", "evidence_files", ["dispute_id"])

    # dispute_messages
    op.create_table(
        "dispute_messages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dispute_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("disputes.id"), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_dispute_messages_dispute", "dispute_messages", ["dispute_id"])

    # audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="user"),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_audit_org", "audit_log", ["organization_id"])
    op.create_index("idx_audit_tournament", "audit_log", ["tournament_id"])
    op.create_index("idx_audit_actor", "audit_log", ["actor_id"])
    op.create_index("idx_audit_action", "audit_log", ["action"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=True),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_notifications_recipient", "notifications", ["recipient_id"])
    op.create_index("idx_notifications_tournament", "notifications", ["tournament_id"])

    # ai_sessions
    op.create_table(
        "ai_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("guild_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tournaments.id"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thread_id", sa.String(20), nullable=True),
        sa.Column("messages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("escalated_to", postgresql.UUID(as_uuid=False), sa.ForeignKey("disputes.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_ai_sessions_org", "ai_sessions", ["organization_id"])
    op.create_index("idx_ai_sessions_tournament", "ai_sessions", ["tournament_id"])
    op.create_index("idx_ai_sessions_user", "ai_sessions", ["user_id"])

    # background_jobs
    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_jobs_status_run", "background_jobs", ["status", "run_after"])


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("ai_sessions")
    op.drop_table("notifications")
    op.drop_table("audit_log")
    op.drop_table("dispute_messages")
    op.drop_index("idx_evidence_dispute", "evidence_files")
    op.drop_column("evidence_files", "dispute_id")
    op.drop_table("disputes")
    op.drop_table("checkins")
    op.drop_table("standings")
    op.drop_table("battle_royale_results")
    op.drop_table("matches")
    op.drop_table("brackets")
    op.drop_table("team_members")
    op.drop_table("registrations")
    op.drop_table("evidence_files")
    op.drop_table("teams")
    op.drop_table("form_fields")
    op.drop_table("registration_forms")
    op.drop_table("staff_members")
    op.drop_table("tournaments")
    op.drop_table("users")
    op.drop_table("guilds")
    op.drop_table("organizations")
