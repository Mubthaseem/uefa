"""004 Live Events and Streaming Feeds Tables

Revision ID: 004_live_events_and_streams
Revises: 003_code_export
Create Date: 2026-10-26 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "004_live_events_and_streams"
down_revision = "003_code_export"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. live_events table
    op.create_table(
        "live_events",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="Football"),
        sa.Column("league", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("team_home", sa.String(128), nullable=False),
        sa.Column("team_away", sa.String(128), nullable=False),
        sa.Column("team_home_badge", sa.String(512), nullable=True),
        sa.Column("team_away_badge", sa.String(512), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="upcoming"),
        sa.Column("score_home", sa.String(16), nullable=True, server_default="0"),
        sa.Column("score_away", sa.String(16), nullable=True, server_default="0"),
        sa.Column("live_minute", sa.String(32), nullable=True, server_default=""),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("live_events_status_idx", "live_events", ["status"])
    op.create_index("live_events_scheduled_at_idx", "live_events", ["scheduled_at"])

    # 2. event_streams table
    op.create_table(
        "event_streams",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("event_id", sa.CHAR(36), sa.ForeignKey("live_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("stream_type", sa.String(32), nullable=False, server_default="hls"),
        sa.Column("stream_url", sa.String(1024), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=False, server_default="1080p"),
        sa.Column("language", sa.String(32), nullable=False, server_default="English"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("event_streams")
    op.drop_table("live_events")
