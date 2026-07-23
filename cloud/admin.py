"""Admin operations: issue / suspend / revoke activation keys, and safe support
lookup. Every action writes an audit event. The raw key is returned ONCE at
issue and never again — lookups return only non-secret fields.

CLI (secrets from the environment, same as the service):
    python -m cloud.admin issue  --plan pro --uses 1 [--expires-days 365]
    python -m cloud.admin revoke --key-id <id>
    python -m cloud.admin suspend --key-id <id>
    python -m cloud.admin lookup  [--prefix PLASMA-XXXX | --key-id <id>]
"""

from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from . import models
from .audit import record
from .db import create_engine_for, create_session_factory, database_url, utc_now
from .keys import generate_activation_key, key_verifier


def issue_key(
    session,
    *,
    plan_id: str,
    pepper: bytes,
    max_uses: int = 1,
    expires_at: datetime | None = None,
    created_by: str = "admin",
) -> tuple[str, models.ActivationKey]:
    """Create an activation key. Returns (display_key, row). The display key is
    shown to the operator once and never persisted (only its HMAC verifier is)."""
    if session.get(models.Plan, plan_id) is None:
        raise ValueError(f"unknown plan: {plan_id}")
    display, parts = generate_activation_key()
    key = models.ActivationKey(
        verifier=key_verifier(display, pepper),
        lookup_prefix=parts["lookup_prefix"],
        last4=parts["last4"],
        plan_id=plan_id,
        max_uses=max_uses,
        uses_remaining=max_uses,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(key)
    session.flush()
    record(
        session,
        actor=created_by,
        action="key.issue",
        subject_type="activation_key",
        subject_id=key.id,
        data={"plan": plan_id, "max_uses": max_uses},
    )
    return display, key


def set_key_status(session, *, key_id: str, status: str, actor: str = "admin") -> bool:
    if status not in ("active", "suspended", "revoked"):
        raise ValueError(f"invalid status: {status}")
    key = session.get(models.ActivationKey, key_id)
    if key is None:
        return False
    key.status = status
    record(
        session,
        actor=actor,
        action=f"key.{status}",
        subject_type="activation_key",
        subject_id=key_id,
    )
    return True


def lookup_key(
    session, *, lookup_prefix: str | None = None, key_id: str | None = None
) -> list[dict[str, Any]]:
    """Support lookup — never returns the key, only safe fields."""
    statement = select(models.ActivationKey)
    if key_id:
        statement = statement.where(models.ActivationKey.id == key_id)
    elif lookup_prefix:
        statement = statement.where(models.ActivationKey.lookup_prefix == lookup_prefix)
    else:
        return []
    return [
        {
            "key_id": key.id,
            "lookup_prefix": key.lookup_prefix,
            "last4": key.last4,
            "plan": key.plan_id,
            "status": key.status,
            "uses_remaining": key.uses_remaining,
            "max_uses": key.max_uses,
            "created_at": key.created_at.isoformat(),
        }
        for key in session.scalars(statement)
    ]


def _cli() -> None:
    parser = argparse.ArgumentParser(prog="cloud.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue", help="mint an activation key")
    issue.add_argument("--plan", required=True)
    issue.add_argument("--uses", type=int, default=1)
    issue.add_argument("--expires-days", type=int)
    for name in ("revoke", "suspend"):
        p = sub.add_parser(name)
        p.add_argument("--key-id", required=True)
    look = sub.add_parser("lookup")
    look.add_argument("--prefix")
    look.add_argument("--key-id")
    args = parser.parse_args()

    factory = create_session_factory(create_engine_for(database_url()))
    with factory() as session:
        if args.cmd == "issue":
            pepper = base64.b64decode(os.environ["PLASMA_ACTIVATION_PEPPER"])
            expires = (
                utc_now() + timedelta(days=args.expires_days) if args.expires_days else None
            )
            display, key = issue_key(
                session,
                plan_id=args.plan,
                pepper=pepper,
                max_uses=args.uses,
                expires_at=expires,
            )
            session.commit()
            print("Activation key (store now — shown once):")
            print(f"  {display}")
            print(f"  key_id={key.id}  prefix={key.lookup_prefix}")
        elif args.cmd in ("revoke", "suspend"):
            status = "revoked" if args.cmd == "revoke" else "suspended"
            ok = set_key_status(session, key_id=args.key_id, status=status)
            session.commit()
            print("ok" if ok else "key not found")
        elif args.cmd == "lookup":
            rows = lookup_key(session, lookup_prefix=args.prefix, key_id=args.key_id)
            for row in rows:
                print(row)
            if not rows:
                print("no match")


if __name__ == "__main__":  # pragma: no cover
    _cli()
