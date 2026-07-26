"""Super-admin HTTP surface.

Administration was CLI-only (cloud/admin.py). These routes expose the same
operations to the dashboard, with two rules that the CLI did not need:

  * every request is gated on the caller's stored role being 'admin' - read from
    the database on each request, never trusted from the token, so revoking an
    admin takes effect immediately rather than at token expiry;
  * every mutation writes an AuditEvent. Admin actions change what customers paid
    for, so "who did this" must always be answerable.

Anyone reaching this surface can mint licences, so it is deliberately narrow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from pathlib import Path

from typing import Union
from fastapi import APIRouter, Depends, Query, Request
from fastapi import Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import admin as admin_ops
from ... import audit, models
from ... import throttle
from ...deps import get_session, require_access
from ...features.auth import service as auth_service
from ...tokens import mint_access_token
from ...errors import CloudError


router = APIRouter(prefix="/admin", tags=["admin"])
_STATIC = Path(__file__).with_name("static")
_DIST = _STATIC / "dist"
_INDEX = _DIST / "index.html"
_PAGE_FALLBACK = _STATIC / "index.html"


@router.get("/admin.css", include_in_schema=False)
def dashboard_css() -> Response:
    """Generated from manager/frontend's own Tailwind config and tokens, so the
    dashboard cannot drift from the product's design system."""
    return Response(
        (_STATIC / "admin.css").read_text(encoding="utf-8"),
        media_type="text/css",
    )




def _get_dashboard_page() -> HTMLResponse:
    """The dashboard HTML. Never cached: it is the one URL that must always
    point at the current hashed bundle names."""
    page = _INDEX if _INDEX.exists() else _PAGE_FALLBACK
    return HTMLResponse(
        page.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache"},
    )


SessionDep = Annotated[Session, Depends(get_session)]


def require_admin(
    session: SessionDep, claims: dict = Depends(require_access)
) -> models.User:
    """The caller, only if their *stored* role is admin.

    Deliberately re-read per request instead of trusting a role claim in the
    token: demoting or suspending an admin must take effect at once, not whenever
    their access token happens to expire.
    """
    user = session.get(models.User, claims.get("sub"))
    if user is None or user.role != "admin" or user.status != "active":
        raise CloudError("admin_forbidden")
    return user


AdminDep = Annotated[models.User, Depends(require_admin)]


# --------------------------------------------------------------------------- #
# Admin sign-in
# --------------------------------------------------------------------------- #

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    email: EmailStr


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest, request: Request, session: SessionDep):
    """Email + password only.

    The customer login binds a session to a device with an Ed25519 signature; an
    admin is not running the product, so requiring a registered device would be
    ceremony without benefit. Same throttle as the customer path, and a failure
    here is deliberately indistinguishable from a non-admin account.
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    identifier = str(payload.email)
    try:
        throttle.enforce_not_locked(factory, scope="admin-login", identifier=identifier)
    except throttle.ThrottleError as error:
        raise CloudError("throttled") from error
    try:
        user = auth_service.authenticate(session, email=payload.email, password=payload.password)
    except Exception as error:
        throttle.record_failure(factory, scope="admin-login", identifier=identifier,
                                max_attempts=5, lockout=timedelta(minutes=15))
        raise CloudError("unauthorized") from error
    if user.role != "admin" or user.status != "active":
        # Same error as bad credentials: do not reveal that the account exists.
        throttle.record_failure(factory, scope="admin-login", identifier=identifier,
                                max_attempts=5, lockout=timedelta(minutes=15))
        raise CloudError("unauthorized")
    throttle.record_success(factory, scope="admin-login", identifier=identifier)
    token = mint_access_token(
        user_id=user.id,
        session_id="admin",
        device_id="admin",
        private_key=settings.signing_private_key,
        now=datetime.now(timezone.utc),
        ttl=timedelta(hours=8),
    )
    audit.record(
        session, actor=user.email, action="admin.login",
        subject_type="user", subject_id=user.id, data={},
    )
    session.commit()
    return {"access_token": token, "email": user.email}


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

class UserRead(BaseModel):
    id: str
    email: EmailStr
    status: str
    role: str
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserRead]
    total: int


class UserStatusRequest(BaseModel):
    status: Literal["active", "suspended"]


@router.get("/users", response_model=UserPage)
def list_users(
    session: SessionDep,
    _admin: AdminDep,
    query: str | None = Query(default=None, description="email contains"),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    statement = select(models.User)
    counter = select(func.count(models.User.id))
    if query:
        clause = models.User.email.contains(query.strip().casefold())
        statement, counter = statement.where(clause), counter.where(clause)
    if status:
        statement, counter = (
            statement.where(models.User.status == status),
            counter.where(models.User.status == status),
        )
    rows = session.scalars(
        statement.order_by(models.User.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return {"items": list(rows), "total": int(session.scalar(counter) or 0)}


@router.get("/users/{user_id}")
def get_user(user_id: str, session: SessionDep, _admin: AdminDep) -> dict[str, Any]:
    """A user with the context support actually needs: their seats and licences."""
    user = session.get(models.User, user_id)
    if user is None:
        raise CloudError("not_found")
    devices = session.scalars(
        select(models.Device).where(models.Device.user_id == user_id)
    ).all()
    redemptions = session.scalars(
        select(models.Redemption).where(models.Redemption.user_id == user_id)
    ).all()
    plan = _effective_plan(session, user_id)
    return {
        "user": UserRead.model_validate(user, from_attributes=True).model_dump(),
        "plan": (
            {"id": plan.id, "name": plan.name, "max_devices": plan.max_devices}
            if plan is not None
            else None
        ),
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "platform": d.platform,
                "created_at": d.created_at,
                "last_seen_at": d.last_seen_at,
                "revoked_at": d.revoked_at,
            }
            for d in devices
        ],
        "redemptions": [
            {
                "id": r.id,
                "key_id": r.key_id,
                "device_id": r.device_id,
                "redeemed_at": r.redeemed_at,
            }
            for r in redemptions
        ],
    }


@router.post("/users/{user_id}/status", response_model=UserRead)
def set_user_status(
    user_id: str, payload: UserStatusRequest, session: SessionDep, admin: AdminDep
):
    """Suspend or restore an account. Suspending also kills live sessions."""
    user = session.get(models.User, user_id)
    if user is None:
        raise CloudError("not_found")
    before = user.status
    if not admin_ops.set_user_status(
        session, email=user.email, status=payload.status, actor=admin.email
    ):
        raise CloudError("not_found")
    audit.record(
        session,
        actor=admin.email,
        action="admin.user.status",
        subject_type="user",
        subject_id=user_id,
        data={"from": before, "to": payload.status},
    )
    session.commit()
    session.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# Activation keys
# --------------------------------------------------------------------------- #

class IssueKeysRequest(BaseModel):
    plan_id: str
    count: int = Field(default=1, ge=1, le=500)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None


class IssuedKey(BaseModel):
    key_id: str
    key: str  # shown once, never stored - only its HMAC verifier is


class KeyStatusRequest(BaseModel):
    status: Literal["active", "suspended", "revoked"]


@router.post("/keys", response_model=list[IssuedKey])
def issue_keys(payload: IssueKeysRequest, request: Request, session: SessionDep, admin: AdminDep):
    """Mint activation keys. The plaintext key is returned once, here, and never
    again - only its verifier is persisted."""
    pepper = request.app.state.settings.activation_pepper
    issued: list[dict[str, str]] = []
    try:
        for _ in range(payload.count):
            display, row = admin_ops.issue_key(
                session,
                plan_id=payload.plan_id,
                pepper=pepper,
                max_uses=payload.max_uses,
                expires_at=payload.expires_at,
                created_by=admin.email,
            )
            issued.append({"key_id": row.id, "key": display})
    except ValueError as error:  # unknown plan
        session.rollback()
        raise CloudError("invalid_request") from error
    audit.record(
        session,
        actor=admin.email,
        action="admin.keys.issue",
        subject_type="plan",
        subject_id=payload.plan_id,
        # The keys themselves are never audited - only how many, for whom.
        data={"count": payload.count, "key_ids": [k["key_id"] for k in issued]},
    )
    session.commit()
    return issued


@router.get("/keys")
def lookup_keys(
    session: SessionDep,
    _admin: AdminDep,
    prefix: str | None = Query(default=None),
    key_id: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Support lookup. Returns safe fields only - never the key."""
    return admin_ops.lookup_key(session, lookup_prefix=prefix, key_id=key_id)


@router.post("/keys/{key_id}/status")
def set_key_status(
    key_id: str, payload: KeyStatusRequest, session: SessionDep, admin: AdminDep
) -> dict[str, str]:
    key = session.get(models.ActivationKey, key_id)
    if key is None:
        raise CloudError("not_found")
    before = key.status
    if not admin_ops.set_key_status(
        session, key_id=key_id, status=payload.status, actor=admin.email
    ):
        raise CloudError("not_found")
    audit.record(
        session,
        actor=admin.email,
        action="admin.key.status",
        subject_type="activation_key",
        subject_id=key_id,
        data={"from": before, "to": payload.status},
    )
    session.commit()
    return {"key_id": key_id, "status": payload.status}


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

@router.get("/plans")
def list_plans(session: SessionDep, _admin: AdminDep) -> list[dict[str, Any]]:
    plans = session.scalars(select(models.Plan).order_by(models.Plan.id)).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "max_devices": p.max_devices,
            "max_profiles": p.max_profiles,
            "max_sessions": p.max_sessions,
            "features": p.features,
        }
        for p in plans
    ]


def _effective_plan(session: Session, user_id: str) -> models.Plan | None:
    """The plan a user is actually on.

    A live subscription wins; otherwise fall back to the plan of the most recent
    key they redeemed, which is how admin-issued licences (the v1 path) work.
    """
    subscription = session.scalars(
        select(models.Subscription)
        .where(models.Subscription.user_id == user_id, models.Subscription.status == "active")
        .order_by(models.Subscription.created_at.desc())
    ).first()
    if subscription is not None:
        return session.get(models.Plan, subscription.plan_id)
    redemption = session.scalars(
        select(models.Redemption)
        .where(models.Redemption.user_id == user_id)
        .order_by(models.Redemption.redeemed_at.desc())
    ).first()
    if redemption is None:
        return None
    key = session.get(models.ActivationKey, redemption.key_id)
    return session.get(models.Plan, key.plan_id) if key is not None else None


# --------------------------------------------------------------------------- #
# Seats / devices - the most-used support action
# --------------------------------------------------------------------------- #

@router.post("/devices/{device_id}/release")
def release_device(device_id: str, session: SessionDep, admin: AdminDep) -> dict[str, Any]:
    """Free the seat a device holds.

    'I reinstalled Windows and cannot activate' is the most common licensing
    ticket; before this it needed manual database work.
    """
    device = session.get(models.Device, device_id)
    if device is None:
        raise CloudError("not_found")
    # Seat counting filters on revoked_at (see the ix_devices_user_active index),
    # so stamping it is what actually frees the seat.
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
    audit.record(
        session,
        actor=admin.email,
        action="admin.device.release",
        subject_type="device",
        subject_id=device_id,
        data={"user_id": device.user_id},
    )
    session.commit()
    return {"device_id": device_id, "revoked_at": device.revoked_at.isoformat()}


# --------------------------------------------------------------------------- #
# Releases
# --------------------------------------------------------------------------- #

class ReleaseRequest(BaseModel):
    channel: Literal["stable", "beta"] = "stable"
    version: str = Field(min_length=1, max_length=32)
    min_supported_version: str = Field(min_length=1, max_length=32)
    artifact_url: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    signature: str = Field(min_length=1)


@router.get("/releases")
def list_releases(session: SessionDep, _admin: AdminDep) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(models.UpdateRelease).order_by(models.UpdateRelease.published_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "channel": r.channel,
            "version": r.version,
            "min_supported_version": r.min_supported_version,
            "artifact_url": r.artifact_url,
            "sha256": r.sha256,
            "published_at": r.published_at,
        }
        for r in rows
    ]


@router.post("/releases")
def publish_release(
    payload: ReleaseRequest, session: SessionDep, admin: AdminDep
) -> dict[str, Any]:
    """Publish an update. Every client on the channel will be offered this, so the
    checksum and signature are recorded exactly as given - the updater verifies
    them, and a wrong value here is a failed update for everyone, not a silent one.
    """
    existing = session.scalars(
        select(models.UpdateRelease).where(
            models.UpdateRelease.channel == payload.channel,
            models.UpdateRelease.version == payload.version,
        )
    ).first()
    if existing is not None:
        # Releases are immutable: re-publishing a version would change what
        # already-updated clients were told they installed.
        raise CloudError("redeem_conflict")
    release = models.UpdateRelease(**payload.model_dump())
    session.add(release)
    audit.record(
        session,
        actor=admin.email,
        action="admin.release.publish",
        subject_type="release",
        subject_id=payload.version,
        data={"channel": payload.channel, "sha256": payload.sha256},
    )
    session.commit()
    session.refresh(release)
    return {"id": release.id, "channel": release.channel, "version": release.version}


# --------------------------------------------------------------------------- #
# Overview + audit
# --------------------------------------------------------------------------- #

@router.get("/overview")
def overview(session: SessionDep, _admin: AdminDep) -> dict[str, int]:
    """The few numbers that answer most questions. Deliberately not a BI project."""
    now = datetime.now(timezone.utc)
    return {
        "users": int(session.scalar(select(func.count(models.User.id))) or 0),
        "users_suspended": int(
            session.scalar(
                select(func.count(models.User.id)).where(models.User.status == "suspended")
            ) or 0
        ),
        "keys": int(session.scalar(select(func.count(models.ActivationKey.id))) or 0),
        "keys_active": int(
            session.scalar(
                select(func.count(models.ActivationKey.id)).where(
                    models.ActivationKey.status == "active"
                )
            ) or 0
        ),
        "redemptions": int(session.scalar(select(func.count(models.Redemption.id))) or 0),
        "keys_expiring_30d": int(
            session.scalar(
                select(func.count(models.ActivationKey.id)).where(
                    models.ActivationKey.expires_at.is_not(None),
                    models.ActivationKey.expires_at > now,
                    models.ActivationKey.expires_at < now + timedelta(days=30),
                )
            ) or 0
        ),
    }


@router.get("/audit")
def audit_log(
    session: SessionDep,
    _admin: AdminDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "actor": e.actor,
            "action": e.action,
            "subject_type": e.subject_type,
            "subject_id": e.subject_id,
            "data": e.data,
            "created_at": e.created_at,
        }
        for e in rows
    ]


# MUST stay the last route on this router: Starlette matches in registration
# order, and this catch-all registered any earlier shadowed every admin GET
# API above (they returned the SPA HTML instead of JSON).
@router.get("/{path_name:path}", include_in_schema=False)
def dashboard_spa(path_name: str):
    """SPA fallback - serve index.html for all non-API routes under /admin."""
    if path_name.startswith("dist/"):
        file_full_path = (_DIST / path_name[5:]).resolve()
        if file_full_path.exists() and str(file_full_path).startswith(str(_DIST)):
            # Bundle filenames are content-hashed, so edge/browser caches may
            # keep them forever; a new build references new names.
            return FileResponse(
                file_full_path,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
    return _get_dashboard_page()


