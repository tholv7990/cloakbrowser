"""Templates, credential pool, and recording lifecycle.

Website credentials never touch the DB or templates: fill steps store a
``{"variable": "email"}`` reference, and pooled secrets live in the secure
CredentialStore keyed by a ref — the DB holds only a SHA-256 fingerprint + status.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import (
    AutomationCredential,
    AutomationRecording,
    AutomationTemplate,
    Profile,
)
from ..proxies.credentials import CredentialStore, ProxyCredential
from .controller import AutomationController


CREDENTIAL_VARIABLES = ("email", "password")


# --- shared helpers ---------------------------------------------------------
def variables_from_steps(steps: list[dict]) -> list[str]:
    seen: list[str] = []
    for step in steps:
        variable = step.get("variable")
        if variable and variable not in seen:
            seen.append(variable)
    return seen


def template_to_dict(template: AutomationTemplate) -> dict:
    steps = list(template.steps_json or [])
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "steps": steps,
        "variables": variables_from_steps(steps),
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def recording_to_dict(recording: AutomationRecording) -> dict:
    return {
        "id": recording.id,
        "name": recording.name,
        "description": recording.description,
        "profile_id": recording.profile_id,
        "status": recording.status,
        "step_count": recording.step_count,
        "template_id": recording.template_id,
        "created_at": recording.created_at,
    }


# --- templates --------------------------------------------------------------
def list_templates(session: Session) -> list[dict]:
    templates = session.scalars(
        select(AutomationTemplate).order_by(
            AutomationTemplate.updated_at.desc(), AutomationTemplate.id
        )
    ).all()
    return [template_to_dict(template) for template in templates]


def get_template(session: Session, template_id: str) -> AutomationTemplate:
    template = session.get(AutomationTemplate, template_id)
    if template is None:
        raise ManagerError("template_not_found", "The requested template was not found.", 404)
    return template


def save_template(
    session: Session, template_id: str, *, name: str, description: str, steps: list[dict]
) -> dict:
    template = session.get(AutomationTemplate, template_id)
    if template is None:
        template = AutomationTemplate(id=template_id)
        session.add(template)
    template.name = name.strip()
    template.description = description
    template.steps_json = steps
    session.commit()
    session.refresh(template)
    return template_to_dict(template)


def delete_template(session: Session, template_id: str) -> None:
    template = get_template(session, template_id)
    session.delete(template)
    session.commit()


# --- credential pool --------------------------------------------------------
def _fingerprint(email: str, password: str) -> str:
    return hashlib.sha256(f"{email}:{password}".encode("utf-8")).hexdigest()


def import_credentials(session: Session, store: CredentialStore, text: str) -> dict:
    added = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        email, password = line.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            continue
        fingerprint = _fingerprint(email, password)
        exists = session.scalar(
            select(AutomationCredential.id).where(
                AutomationCredential.fingerprint_sha256 == fingerprint
            )
        )
        if exists:
            continue
        ref = str(uuid4())
        store.put(ref, ProxyCredential(email, password))
        session.add(
            AutomationCredential(
                fingerprint_sha256=fingerprint, status="available", credential_ref=ref
            )
        )
        added += 1
    session.commit()
    return credential_summary(session)


def credential_summary(session: Session) -> dict:
    rows = session.execute(
        select(AutomationCredential.status, func.count())
        .select_from(AutomationCredential)
        .group_by(AutomationCredential.status)
    ).all()
    counts = {status: int(count) for status, count in rows}
    return {
        "available": counts.get("available", 0),
        "reserved": counts.get("reserved", 0),
        "used": counts.get("used", 0),
        "failed": counts.get("failed", 0),
        "total": sum(counts.values()),
    }


def reserve_credential(
    session: Session, *, run_id: str, profile_id: str, credential_id: str | None
) -> str | None:
    """Atomically reserve a credential; return its store ref, or None if none free.

    The conditional UPDATE (status='available' guard, rowcount==1) makes a
    double-reserve impossible even under concurrent runs.
    """
    if credential_id is not None:
        target = credential_id
    else:
        target = session.scalar(
            select(AutomationCredential.id)
            .where(AutomationCredential.status == "available")
            .order_by(AutomationCredential.created_at)
            .limit(1)
        )
        if target is None:
            return None
    result = session.execute(
        update(AutomationCredential)
        .where(AutomationCredential.id == target, AutomationCredential.status == "available")
        .values(status="reserved", reserved_run_id=run_id, reserved_profile_id=profile_id)
    )
    if result.rowcount != 1:
        return None
    return session.scalar(
        select(AutomationCredential.credential_ref).where(AutomationCredential.id == target)
    )


def complete_credential(session: Session, *, run_id: str, profile_id: str) -> None:
    session.execute(
        update(AutomationCredential)
        .where(
            AutomationCredential.reserved_run_id == run_id,
            AutomationCredential.reserved_profile_id == profile_id,
            AutomationCredential.status == "reserved",
        )
        .values(status="used")
    )
    session.commit()


def release_credential(session: Session, *, run_id: str, profile_id: str) -> None:
    session.execute(
        update(AutomationCredential)
        .where(
            AutomationCredential.reserved_run_id == run_id,
            AutomationCredential.reserved_profile_id == profile_id,
            AutomationCredential.status == "reserved",
        )
        .values(status="available", reserved_run_id=None, reserved_profile_id=None)
    )
    session.commit()


def credential_secret(store: CredentialStore, ref: str) -> tuple[str, str] | None:
    credential = store.get(ref)
    return (credential.username, credential.password) if credential else None


# --- recordings -------------------------------------------------------------
def _get_recording(session: Session, recording_id: str) -> AutomationRecording:
    recording = session.get(AutomationRecording, recording_id)
    if recording is None:
        raise ManagerError("recording_not_found", "The requested recording was not found.", 404)
    return recording


def start_recording(
    session: Session,
    controller: AutomationController,
    *,
    name: str,
    profile_id: str,
    description: str,
) -> dict:
    profile = session.get(Profile, profile_id)
    if profile is None or profile.deleted_at is not None:
        raise ManagerError("profile_not_found", "The profile was not found.", 404)
    recording = AutomationRecording(
        name=name.strip(), description=description, profile_id=profile_id, status="recording"
    )
    controller.start_recording(recording.id, profile_id)  # raises before we persist if unavailable
    session.add(recording)
    session.commit()
    session.refresh(recording)
    return recording_to_dict(recording)


def get_recording(
    session: Session, controller: AutomationController, recording_id: str
) -> dict:
    recording = _get_recording(session, recording_id)
    if recording.status == "recording":
        recording.step_count = controller.recording_step_count(recording_id)
        session.commit()
    return recording_to_dict(recording)


def stop_recording(
    session: Session, controller: AutomationController, recording_id: str
) -> dict:
    recording = _get_recording(session, recording_id)
    if recording.status != "recording":
        raise ManagerError("recording_not_active", "This recording is not active.", 400)
    steps = controller.finish_recording(recording_id)
    template = AutomationTemplate(
        name=recording.name, description=recording.description, steps_json=steps
    )
    session.add(template)
    session.flush()
    recording.status = "stopped"
    recording.template_id = template.id
    recording.step_count = len(steps)
    session.commit()
    session.refresh(template)
    return template_to_dict(template)


def cancel_recording(
    session: Session, controller: AutomationController, recording_id: str
) -> None:
    recording = _get_recording(session, recording_id)
    if recording.status == "recording":
        controller.cancel_recording(recording_id)
        recording.status = "cancelled"
        session.commit()
