"""
v2 columns — autonomous_mode, team_hub_config, match_channel_config, group_config,
and registration status updates (waitlisted, checked_in).

Revision ID: 003_v2_columns
Revises: 002_scheduling_columns
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003_v2_columns"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Tournament 2.0 columns ────────────────────────────────────────────────
    op.add_column(
        "tournaments",
        sa.Column("autonomous_mode", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "tournaments",
        sa.Column("team_hub_config", JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tournaments",
        sa.Column("match_channel_config", JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tournaments",
        sa.Column("group_config", JSONB(), nullable=False, server_default="{}"),
    )

    # ── Add new tournament formats ────────────────────────────────────────────
    # formats stored as VARCHAR — just add new enum values via ALTER TYPE or
    # leave as string column (native_enum=False, so no ALTER needed)

    # ── Registration status additions ────────────────────────────────────────
    # RegistrationStatus stored as VARCHAR (native_enum=False), so new values
    # are automatically accepted by the application without DDL changes.
    # Migrate existing HOLD rows → WAITLISTED for clarity.
    op.execute(
        "UPDATE registrations SET status = 'waitlisted' WHERE status = 'hold'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE registrations SET status = 'hold' WHERE status = 'waitlisted'"
    )
    op.drop_column("tournaments", "group_config")
    op.drop_column("tournaments", "match_channel_config")
    op.drop_column("tournaments", "team_hub_config")
    op.drop_column("tournaments", "autonomous_mode")
