"""Cloud control-plane data model.

Design rules baked in here:
- No secret is ever stored in plaintext. Passwords → argon2id hash. Activation
  keys → keyed HMAC verifier (see ``keys.py``). Email/reset/refresh tokens → SHA-256
  digests. There is intentionally NO column that holds a raw key/token/password.
- Race-safety is enforced by the schema, not just app code: one-time redemption is
  a UNIQUE constraint; device/session identity is unique; so two concurrent writers
  cannot both win.
- Types are portable (String/JSON/DateTime(timezone=True)) so the same models run on
  PostgreSQL (prod) and SQLite (tests).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, new_id, utc_now


# --- Accounts -----------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # argon2id hash only — never the password.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified")
    # Real identity for the audit trail (audit_events.actor references a user id or
    # the literal "system"); admins issue/revoke keys and devices.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="user")

    __table_args__ = (
        # Email is normalized (NFC + casefold) by the app before insert, so a plain
        # unique gives case-insensitive uniqueness on SQLite (tests). The Alembic
        # migration ADDS a Postgres functional unique index on lower(email) as
        # DB-level defense-in-depth against an un-normalized insert path.
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(
            "status in ('unverified','active','suspended')", name="ck_users_status"
        ),
        CheckConstraint("role in ('user','admin')", name="ck_users_role"),
    )


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the emailed token — never the token itself.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_email_verif_token"),
        Index("ix_email_verif_user", "user_id"),  # FK cascade + per-user lookup
    )


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_token"),
        Index("ix_password_reset_user", "user_id"),  # FK cascade + per-user lookup
    )


# --- Devices & sessions -------------------------------------------------------


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Ed25519 device public key (base64). The private key never leaves the device.
    public_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Windows PC")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="windows")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="devices")

    __table_args__ = (
        # A given public key registers once per account (idempotent re-register).
        UniqueConstraint("user_id", "public_key", name="uq_device_user_key"),
        # Device-count / limit queries filter by user_id and revoked_at.
        Index("ix_devices_user_active", "user_id", "revoked_at"),
    )


class Session(Base):
    """A refresh-token session. Rotation forms a *family*; presenting an already
    rotated refresh (reuse) revokes the whole family."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    # No default on purpose: a rotation MUST inherit the parent's family_id; only
    # session creation assigns a fresh one. A silent default would fork the family
    # and collapse reuse-revocation scope.
    family_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # SHA-256 of THIS row's refresh token — never the token itself. Rotation APPENDS
    # a new row (setting rotated_at on the old); presenting an already-rotated or
    # revoked row's token = reuse → revoke the whole family. Never overwrite in place.
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reuse_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_session_refresh_hash"),
        Index("ix_sessions_family", "family_id"),
        Index("ix_sessions_user_active", "user_id", "revoked_at"),
        # Device-scoped session revoke when a device is revoked (auth doc).
        Index("ix_sessions_device", "device_id"),
    )


# --- Plans, keys, redemptions, entitlements -----------------------------------


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. "solo","pro"
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    max_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_profiles: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    max_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ActivationKey(Base):
    __tablename__ = "activation_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # HMAC-SHA256(pepper, key) — the only representation of the key we ever store.
    verifier: Mapped[str] = mapped_column(String(64), nullable=False)
    # Non-secret support fields (safe to show a support agent).
    lookup_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    plan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        # Indexed for the constant-time verifier lookup at redemption.
        UniqueConstraint("verifier", name="uq_activation_verifier"),
        Index("ix_activation_lookup_prefix", "lookup_prefix"),
        CheckConstraint("uses_remaining >= 0", name="ck_activation_uses_nonneg"),
        CheckConstraint(
            "status in ('active','suspended','revoked')", name="ck_activation_status"
        ),
    )


class Redemption(Base):
    __tablename__ = "redemptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activation_keys.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # NOT NULL so two NULLs can't defeat the uniqueness below (SQL treats NULLs as
    # distinct). A redemption always binds to the device that consumed the key.
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        # Per-device IDEMPOTENCY: a key redeems at most once on a given device, so a
        # retried redeem can't double-consume. The TOTAL use cap across devices is
        # enforced by an atomic guarded decrement in the redeem transaction
        # (UPDATE activation_keys SET uses_remaining = uses_remaining - 1
        #  WHERE id = :id AND uses_remaining > 0, checking rowcount) — NOT by this
        # constraint. (Index on key_id is redundant with this unique's leading col.)
        UniqueConstraint("key_id", "device_id", name="uq_redemption_key_device"),
        Index("ix_redemptions_user", "user_id"),  # FK cascade + "keys for user"
    )


class Entitlement(Base):
    """Record of an issued entitlement (the signed JWT is derived from this). Kept
    for audit + revocation; the id is the JWT `jti`."""

    __tablename__ = "entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("activation_keys.id", ondelete="SET NULL")
    )
    plan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    offline_grace_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_entitlements_user_device", "user_id", "device_id"),)


class Subscription(Base):
    """Optional for v1 (keys can be admin-issued). Present so a billing provider can
    attach later without a schema break."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_subscriptions_user", "user_id"),
        Index("ix_subscriptions_plan", "plan_id"),  # FK lookup
        CheckConstraint(
            "status in ('active','past_due','canceled','incomplete')",
            name="ck_subscriptions_status",
        ),
    )


# --- Audit & updates ----------------------------------------------------------


class AuditEvent(Base):
    """Append-only security audit trail. Metadata is non-secret only."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)  # admin/system/user id
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. key.redeem
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_ts", "ts"),
        Index("ix_audit_subject", "subject_type", "subject_id"),
    )


class UpdateRelease(Base):
    __tablename__ = "update_releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="stable")
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    min_supported_version: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # Ed25519/minisign
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("channel", "version", name="uq_release_channel_version"),
        Index("ix_releases_channel_published", "channel", "published_at"),
        CheckConstraint("channel in ('stable','beta')", name="ck_release_channel"),
    )


# --- Transient auth/abuse state (DB-backed for v1; no Redis at this scale) ------


class OAuthAuthorizationCode(Base):
    """Short-lived Authorization-Code + PKCE record for the /authorize -> /token
    exchange. Stores the SHA-256 of the code and the PKCE code_challenge (never the
    verifier)."""

    __tablename__ = "oauth_authorization_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)  # S256
    code_challenge_method: Mapped[str] = mapped_column(String(8), nullable=False, default="S256")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_oauth_code_hash"),
        Index("ix_oauth_code_user", "user_id"),
        CheckConstraint(
            "code_challenge_method in ('S256')", name="ck_oauth_pkce_method"
        ),
    )


class IdempotencyKey(Base):
    """Makes a retried mutating request (e.g. redeem) safe: the first response is
    stored and replayed for the same client-supplied key."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "redeem"
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_idempotency_expires", "expires_at"),)


class AuthThrottle(Base):
    """Per-(scope, identifier) attempt counter + lockout for login / reset /
    redeem — the network-facing replacement for the desktop's single global
    in-memory counter."""

    __tablename__ = "auth_throttle"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(24), nullable=False)  # login/reset/redeem
    identifier: Mapped[str] = mapped_column(String(320), nullable=False)  # email or ip
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("scope", "identifier", name="uq_throttle_scope_identifier"),
    )
