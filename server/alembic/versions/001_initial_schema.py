"""001 Initial Schema for DayJournal Service

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-10-26 12:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Admins
    op.create_table(
        "admins",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("mfa_secret", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="support"),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('owner', 'editor', 'support')", name="check_admin_role")
    )
    op.create_index("admins_email_idx", "admins", ["email"])

    # 2. Key Batches
    op.create_table(
        "key_batches",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("created_by", sa.CHAR(36), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_in_days", sa.Integer(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index("key_batches_created_at_idx", "key_batches", ["created_at"])

    # 3. Devices
    op.create_table(
        "devices",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("install_id", sa.CHAR(36), unique=True, nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("platform IN ('android', 'ios') OR platform IS NULL", name="check_device_platform")
    )
    op.create_index("devices_revoked_at_idx", "devices", ["revoked_at"])

    # 4. Access Keys
    op.create_table(
        "access_keys",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("batch_id", sa.CHAR(36), sa.ForeignKey("key_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="unused"),
        sa.Column("device_id", sa.CHAR(36), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('unused', 'redeemed', 'revoked')", name="check_key_status")
    )
    op.create_index("access_keys_status_batch_id_idx", "access_keys", ["status", "batch_id"])
    op.create_index("access_keys_batch_id_idx", "access_keys", ["batch_id"])

    # 5. Entitlements
    op.create_table(
        "entitlements",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("device_id", sa.CHAR(36), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_id", sa.CHAR(36), sa.ForeignKey("access_keys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="check_entitlement_status")
    )
    op.create_index("entitlements_device_id_status_idx", "entitlements", ["device_id", "status"])
    op.create_index("entitlements_expires_at_idx", "entitlements", ["expires_at"])

    # 6. Refresh Tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("device_id", sa.CHAR(36), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", sa.CHAR(36), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("refresh_tokens_family_id_idx", "refresh_tokens", ["family_id"])
    op.create_index("refresh_tokens_device_id_idx", "refresh_tokens", ["device_id"])

    # 7. Feature Flags
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.CHAR(36), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    )

    # 8. App Config
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.CHAR(36), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    )
    op.create_index("app_config_updated_at_idx", "app_config", ["updated_at"])

    # 9. Members Items
    op.create_table(
        "members_items",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("media_ref", sa.String(512), nullable=False),
        sa.Column("thumbnail_ref", sa.String(512), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("min_app_version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("item_type IN ('video', 'audio', 'text')", name="check_item_type")
    )
    op.create_index("members_items_published_sort_idx", "members_items", ["published", "sort_order"])

    # 10. Audit Log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.CHAR(36), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index("audit_log_created_at_idx", "audit_log", ["created_at"])
    op.create_index("audit_log_action_idx", "audit_log", ["action"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("members_items")
    op.drop_table("app_config")
    op.drop_table("feature_flags")
    op.drop_table("refresh_tokens")
    op.drop_table("entitlements")
    op.drop_table("access_keys")
    op.drop_table("devices")
    op.drop_table("key_batches")
    op.drop_table("admins")
