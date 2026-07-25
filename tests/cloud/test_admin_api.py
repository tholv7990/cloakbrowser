"""The admin HTTP surface: it is gated on the stored role and it audits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cloud import models
from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.tokens import mint_access_token


@pytest.fixture
def ctx(tmp_path):
    settings = generate_test_settings()
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    app = create_app(settings, session_factory=factory)

    with factory() as session:
        session.add(
            models.Plan(id="pro", name="Pro", max_devices=3, max_profiles=100, max_sessions=10)
        )
        session.flush()
        admin = models.User(
            email="admin@example.com", password_hash="h", status="active", role="admin"
        )
        member = models.User(email="user@example.com", password_hash="h", status="active")
        session.add_all([admin, member])
        session.flush()
        device = models.Device(user_id=member.id, public_key="pk")
        session.add(device)
        session.commit()
        ids = {"admin": admin.id, "member": member.id, "device": device.id}

    def token(user_id: str) -> str:
        return mint_access_token(
            user_id=user_id,
            session_id="s",
            device_id="d",
            private_key=settings.signing_private_key,
            now=datetime.now(timezone.utc),
            ttl=timedelta(minutes=10),
        )

    return {
        "client": TestClient(app),
        "factory": factory,
        "ids": ids,
        "admin_auth": {"Authorization": f"Bearer {token(ids['admin'])}"},
        "member_auth": {"Authorization": f"Bearer {token(ids['member'])}"},
    }


def _audit(ctx, action):
    with ctx["factory"]() as session:
        return session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.action == action)
        ).all()


def test_a_normal_user_cannot_reach_any_admin_route(ctx):
    """The gate is the whole feature: anyone past it can mint licences."""
    for method, path in (
        ("get", "/admin/users"),
        ("get", "/admin/overview"),
        ("get", "/admin/audit"),
        ("post", "/admin/keys"),
    ):
        kwargs = {"headers": ctx["member_auth"]}
        if method == "post":
            kwargs["json"] = {}
        response = getattr(ctx["client"], method)(path, **kwargs)
        assert response.status_code == 403, path


def test_admin_routes_reject_an_anonymous_caller(ctx):
    assert ctx["client"].get("/admin/users").status_code == 401


def test_demoting_an_admin_takes_effect_immediately_not_at_token_expiry(ctx):
    """The role is re-read per request, so a still-valid token stops working."""
    assert ctx["client"].get("/admin/users", headers=ctx["admin_auth"]).status_code == 200
    with ctx["factory"]() as session:
        session.get(models.User, ctx["ids"]["admin"]).role = "user"
        session.commit()
    assert ctx["client"].get("/admin/users", headers=ctx["admin_auth"]).status_code == 403


def test_listing_and_searching_users(ctx):
    response = ctx["client"].get("/admin/users", headers=ctx["admin_auth"])
    assert response.status_code == 200
    assert response.json()["total"] == 2

    filtered = ctx["client"].get(
        "/admin/users", headers=ctx["admin_auth"], params={"query": "user@"}
    )
    assert [u["email"] for u in filtered.json()["items"]] == ["user@example.com"]


def test_suspending_a_user_is_recorded_with_before_and_after(ctx):
    response = ctx["client"].post(
        f"/admin/users/{ctx['ids']['member']}/status",
        headers=ctx["admin_auth"],
        json={"status": "suspended"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"

    events = _audit(ctx, "admin.user.status")
    assert len(events) == 1
    assert events[0].actor == "admin@example.com"
    assert events[0].data == {"from": "active", "to": "suspended"}


def test_issuing_keys_returns_them_once_and_audits_only_their_ids(ctx):
    response = ctx["client"].post(
        "/admin/keys", headers=ctx["admin_auth"], json={"plan_id": "pro", "count": 3}
    )
    assert response.status_code == 200
    issued = response.json()
    assert len(issued) == 3
    assert all(item["key"] for item in issued)

    events = _audit(ctx, "admin.keys.issue")
    assert len(events) == 1
    assert events[0].data["count"] == 3
    # The audit trail must never carry the key material itself.
    serialized = str(events[0].data)
    assert all(item["key"] not in serialized for item in issued)


def test_issuing_against_an_unknown_plan_is_rejected(ctx):
    response = ctx["client"].post(
        "/admin/keys", headers=ctx["admin_auth"], json={"plan_id": "nope", "count": 1}
    )
    assert response.status_code == 400


def test_releasing_a_device_frees_the_seat_and_is_audited(ctx):
    """The most common licensing ticket: reinstalled machine, cannot activate."""
    response = ctx["client"].post(
        f"/admin/devices/{ctx['ids']['device']}/release", headers=ctx["admin_auth"]
    )
    assert response.status_code == 200
    with ctx["factory"]() as session:
        assert session.get(models.Device, ctx["ids"]["device"]).revoked_at is not None
    assert len(_audit(ctx, "admin.device.release")) == 1


def test_overview_counts_users_and_keys(ctx):
    ctx["client"].post(
        "/admin/keys", headers=ctx["admin_auth"], json={"plan_id": "pro", "count": 2}
    )
    body = ctx["client"].get("/admin/overview", headers=ctx["admin_auth"]).json()
    assert body["users"] == 2
    assert body["keys"] == 2
    assert body["keys_active"] == 2
