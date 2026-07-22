from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


profile_tags = Table(
    "profile_tags",
    Base.metadata,
    Column("profile_id", String(36), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


profile_extensions = Table(
    "profile_extensions",
    Base.metadata,
    Column(
        "profile_id",
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "extension_id",
        String(36),
        ForeignKey("extensions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Folder(TimestampMixin, Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profiles: Mapped[list["Profile"]] = relationship(back_populates="folder")


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748B")
    profiles: Mapped[list["Profile"]] = relationship(
        secondary=profile_tags, back_populates="tags"
    )


class WorkflowStatus(TimestampMixin, Base):
    __tablename__ = "workflow_statuses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748B")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profiles: Mapped[list["Profile"]] = relationship(back_populates="workflow_status")


class Proxy(TimestampMixin, Base):
    __tablename__ = "proxies"
    __table_args__ = (
        CheckConstraint(
            "scheme IN ('direct','http','https','socks5','socks5h')",
            name="ck_proxies_scheme",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(120, collation="NOCASE"), nullable=False, unique=True)
    scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    test_before_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exit_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    asn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(160), nullable=True)
    proxy_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    type_confidence: Mapped[float | None] = mapped_column(nullable=True)
    reputation: Mapped[str | None] = mapped_column(String(24), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profiles: Mapped[list["Profile"]] = relationship(back_populates="proxy")
    quality_runs: Mapped[list["ProxyQualityRun"]] = relationship(
        back_populates="proxy", cascade="all, delete-orphan"
    )


class ProxyQualityRun(Base):
    __tablename__ = "proxy_quality_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','running','completed','failed','cancelled')",
            name="ck_proxy_quality_runs_state",
        ),
        Index(
            "uq_proxy_quality_runs_active_proxy",
            "proxy_id",
            unique=True,
            sqlite_where=text("state IN ('queued','running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proxy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("proxies.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    report: Mapped[dict[str, Any] | None] = mapped_column("report_json", JSON, nullable=True)
    last_message: Mapped[str] = mapped_column(String(80), nullable=False, default="queued")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    proxy: Mapped[Proxy] = relationship(back_populates="quality_runs")


class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "fingerprint_preset IN ('default', 'consistent')",
            name="ck_profiles_fingerprint_preset",
        ),
        CheckConstraint(
            "browser_version_mode IN ('installed', 'pinned')",
            name="ck_profiles_browser_version_mode",
        ),
        CheckConstraint(
            "user_agent_mode IN ('automatic', 'custom')",
            name="ck_profiles_user_agent_mode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    status_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_statuses.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    startup_urls: Mapped[list[str]] = mapped_column("startup_urls_json", JSON, default=list, nullable=False)
    fingerprint_seed: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    fingerprint_preset: Mapped[str] = mapped_column(
        String(16), nullable=False, default="consistent"
    )
    fingerprint_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fingerprint_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_version_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="installed")
    browser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_agent_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="automatic")
    custom_user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    location: Mapped[dict[str, Any]] = mapped_column(
        "location_json", JSON, default=lambda: {"geo_mode": "system"}, nullable=False
    )
    window: Mapped[dict[str, Any]] = mapped_column(
        "window_json", JSON, default=lambda: {"mode": "maximized"}, nullable=False
    )
    behavior: Mapped[dict[str, Any]] = mapped_column(
        "behavior_json", JSON, default=lambda: {"humanize_enabled": False}, nullable=False
    )
    proxy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("proxies.id", ondelete="RESTRICT"), nullable=True
    )
    test_proxy_before_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runtime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    folder: Mapped[Folder | None] = relationship(back_populates="profiles")
    workflow_status: Mapped[WorkflowStatus | None] = relationship(back_populates="profiles")
    proxy: Mapped[Proxy | None] = relationship(back_populates="profiles")
    tags: Mapped[list[Tag]] = relationship(secondary=profile_tags, back_populates="profiles")
    runtime_sessions: Mapped[list["RuntimeSession"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    extensions: Mapped[list["Extension"]] = relationship(
        secondary=profile_extensions, back_populates="profiles"
    )
    diagnostic_runs: Mapped[list["DiagnosticRun"]] = relationship(
        back_populates="profile", passive_deletes=True
    )

    @property
    def runtime_state(self) -> str:
        active = {"queued", "starting", "running", "stopping", "detached"}
        current = next(
            (runtime for runtime in reversed(self.runtime_sessions) if runtime.state in active),
            None,
        )
        return current.state if current is not None else "stopped"


class Extension(TimestampMixin, Base):
    __tablename__ = "extensions"
    __table_args__ = (
        CheckConstraint(
            "manifest_version IN (2, 3)", name="ck_extensions_manifest_version"
        ),
        Index("uq_extensions_directory", "directory", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    directory: Mapped[str] = mapped_column(String(2048, collation="NOCASE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        "permissions_json", JSON, nullable=False, default=list
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    profiles: Mapped[list[Profile]] = relationship(
        secondary=profile_extensions, back_populates="extensions"
    )


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('direct_google_control','pixelscan','iphey','cloudflare','google_search')",
            name="ck_diagnostic_runs_kind",
        ),
        CheckConstraint(
            "status IN ('queued','running','passed','warning','failed','cancelled')",
            name="ck_diagnostic_runs_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_diagnostic_runs_progress",
        ),
        Index(
            "uq_diagnostic_runs_active_profile",
            "profile_id",
            unique=True,
            sqlite_where=text(
                "profile_id IS NOT NULL AND status IN ('queued','running')"
            ),
        ),
        Index(
            "ix_diagnostic_runs_requested_at", "requested_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    findings: Mapped[dict[str, Any]] = mapped_column(
        "findings_json", JSON, nullable=False, default=dict
    )
    screenshot_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    profile: Mapped[Profile | None] = relationship(back_populates="diagnostic_runs")


class RuntimeSession(Base):
    __tablename__ = "runtime_sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','starting','running','stopping','stopped','crashed','detached')",
            name="ck_runtime_sessions_state",
        ),
        Index(
            "uq_runtime_sessions_active_profile",
            "profile_id",
            unique=True,
            sqlite_where=text(
                "state IN ('queued','starting','running','stopping','detached')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    manager_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    manager_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manager_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    browser_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    browser_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cdp_endpoint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_message: Mapped[str] = mapped_column(String(120), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    profile: Mapped[Profile] = relationship(back_populates="runtime_sessions")


class ProfileLogEntry(Base):
    __tablename__ = "profile_log_entries"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug','info','warning','error')",
            name="ck_profile_log_entries_level",
        ),
        Index("ix_profile_log_entries_profile_created_at", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(String(4000), nullable=False)


class Owner(TimestampMixin, Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: "local-owner")
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[Owner] = relationship(back_populates="sessions")
