"""
004 — tournament_snapshots table + feature_flags column on tournaments.

Revision ID: 004_snapshots_and_feature_flags
Revises: 003_v2_columns
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004_snapshots_and_feature_flags"
down_revision = "003_v2_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tournament_snapshots ──────────────────────────────────────────────────
    op.create_table(
        "tournament_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, index=True),
        sa.Column("tournament_id", sa.String(36), nullable=False, index=True),
        sa.Column("trigger", sa.String(50), nullable=False, index=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("state", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # ── feature_flags on tournaments ──────────────────────────────────────────
    # Stored as JSONB to allow arbitrary per-tournament feature toggles
    # without future schema changes.
    # Example: {"score_auto_approval": true, "checkin_required": false}
    op.add_column(
        "tournaments",
        sa.Column("feature_flags", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("tournaments", "feature_flags")
    op.drop_table("tournament_snapshots")
