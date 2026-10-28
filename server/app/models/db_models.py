"""SQLAlchemy 2.0 Database Models for Supabase PostgreSQL (and SQLite test compatibility)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR, JSON, TypeDecorator


class Base(DeclarativeBase):
    """Base class for all ORM models."""


# Cross-dialect UUID type helper
class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.
    Uses PostgreSQL UUID type on Postgres, CHAR(36) on SQLite.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value) if dialect.name != "postgresql" else value
        return str(uuid.UUID(str(value))) if dialect.name != "postgresql" else uuid.UUID(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# Cross-dialect JSONB helper
class SafeJSON(TypeDecorator):
    """Platform-independent JSON type. Uses JSONB on PostgreSQL and JSON on SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(JSON)


# =====================================================================
# 5.1 admins
# =====================================================================
class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'support')", name="check_admin_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    mfa_secret: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="support", nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


# =====================================================================
# 5.2 key_batches
# =====================================================================
class KeyBatch(Base):
    __tablename__ = "key_batches"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_in_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    keys: Mapped[list["AccessKey"]] = relationship("AccessKey", back_populates="batch", cascade="all, delete-orphan")


# =====================================================================
# 5.3 access_keys
# =====================================================================
class AccessKey(Base):
    __tablename__ = "access_keys"
    __table_args__ = (
        CheckConstraint("status IN ('unused', 'redeemed', 'revoked')", name="check_key_status"),
        Index("access_keys_status_batch_id_idx", "status", "batch_id"),
        Index("access_keys_batch_id_idx", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("key_batches.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unused", nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plaintext_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    batch: Mapped["KeyBatch"] = relationship("KeyBatch", back_populates="keys")


# =====================================================================
# 5.4 devices
# =====================================================================
class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("platform IN ('android', 'ios') OR platform IS NULL", name="check_device_platform"),
        Index("devices_revoked_at_idx", "revoked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    install_id: Mapped[uuid.UUID | None] = mapped_column(GUID, unique=True, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    entitlements: Mapped[list["Entitlement"]] = relationship("Entitlement", back_populates="device", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship("RefreshToken", back_populates="device", cascade="all, delete-orphan")


# =====================================================================
# 5.5 entitlements
# =====================================================================
class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="check_entitlement_status"),
        Index("entitlements_device_id_status_idx", "device_id", "status"),
        Index("entitlements_expires_at_idx", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    key_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("access_keys.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="entitlements")
    access_key: Mapped["AccessKey"] = relationship("AccessKey")


# =====================================================================
# 5.6 refresh_tokens
# =====================================================================
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("refresh_tokens_family_id_idx", "family_id"),
        Index("refresh_tokens_device_id_idx", "device_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="refresh_tokens")


# =====================================================================
# 5.7 feature_flags
# =====================================================================
class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(SafeJSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)


# =====================================================================
# 5.8 app_config
# =====================================================================
class AppConfig(Base):
    __tablename__ = "app_config"
    __table_args__ = (
        Index("app_config_updated_at_idx", "updated_at"),
    )

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(SafeJSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)


# =====================================================================
# 5.9 members_items
# =====================================================================
class MembersItem(Base):
    __tablename__ = "members_items"
    __table_args__ = (
        CheckConstraint("item_type IN ('video', 'audio', 'text')", name="check_item_type"),
        Index("members_items_published_sort_idx", "published", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


# =====================================================================
# 5.10 audit_log
# =====================================================================
class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("audit_log_created_at_idx", "created_at"),
        Index("audit_log_action_idx", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", SafeJSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# =====================================================================
# 5.11 live_events (Live Matches / Fixtures)
# =====================================================================
class LiveEvent(Base):
    __tablename__ = "live_events"
    __table_args__ = (
        Index("live_events_status_idx", "status"),
        Index("live_events_scheduled_at_idx", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(64), default="Football", nullable=False)
    league: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    team_home: Mapped[str] = mapped_column(String(128), nullable=False)
    team_away: Mapped[str] = mapped_column(String(128), nullable=False)
    team_home_badge: Mapped[str | None] = mapped_column(String(512), nullable=True)
    team_away_badge: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="upcoming", nullable=False)
    score_home: Mapped[str | None] = mapped_column(String(16), default="0", nullable=True)
    score_away: Mapped[str | None] = mapped_column(String(16), default="0", nullable=True)
    live_minute: Mapped[str | None] = mapped_column(String(32), default="", nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fotmob_match_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fotmob_data: Mapped[dict | None] = mapped_column(SafeJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    streams: Mapped[list["EventStream"]] = relationship("EventStream", back_populates="event", cascade="all, delete-orphan")


# =====================================================================
# 5.12 event_streams (HLS / DASH Streams & Multi-Angle Feeds)
# =====================================================================
class EventStream(Base):
    __tablename__ = "event_streams"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("live_events.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_type: Mapped[str] = mapped_column(String(32), default="hls", nullable=False)
    stream_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    resolution: Mapped[str] = mapped_column(String(32), default="1080p", nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="English", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    event: Mapped["LiveEvent"] = relationship("LiveEvent", back_populates="streams")


# =====================================================================
# 5.13 portal_templates (Server-rendered Web Portal Templates)
# =====================================================================
class PortalTemplate(Base):
    __tablename__ = "portal_templates"
    __table_args__ = (
        Index("portal_templates_slug_active_idx", "slug", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
