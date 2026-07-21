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
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
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
    proxy_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    test_proxy_before_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runtime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    folder: Mapped[Folder | None] = relationship(back_populates="profiles")
    workflow_status: Mapped[WorkflowStatus | None] = relationship(back_populates="profiles")
    tags: Mapped[list[Tag]] = relationship(secondary=profile_tags, back_populates="profiles")


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
