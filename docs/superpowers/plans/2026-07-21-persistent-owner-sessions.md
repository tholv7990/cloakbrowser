# Persistent Owner Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the single local owner's session valid until explicit revocation, without idle or absolute expiration.

**Architecture:** Remove time-based validation from the session service and remove expiry fields from the API contract. Alembic migration `0004` drops expiry-only database columns while preserving session identifiers, hashes, creation time, and revocation state.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, pytest.

## Global Constraints

- Sessions survive dashboard, manager, browser, and Windows restarts.
- Logout revokes the current session; lock and password change revoke all sessions.
- Store only SHA-256 hashes of opaque session and CSRF tokens.
- Keep `HttpOnly`, `SameSite=Strict`, exact Origin, and CSRF protections.
- Existing unrevoked sessions remain valid after migration.

---

### Task 1: Persistent session service and database migration

**Files:**
- Modify: `tests/manager/test_auth_sessions.py`
- Modify: `manager_backend/auth/sessions.py`
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0004_persistent_owner_sessions.py`

**Interfaces:**
- Consumes: `issue_session(db: Session, owner: Owner) -> IssuedSession` and `validate_session(...) -> ValidatedSession`.
- Produces: the same interfaces without `SessionPolicy` or time-expiry behavior.

- [x] Replace expiry tests with a test that backdates `created_at` and proves validation succeeds.
- [x] Run `pytest tests/manager/test_auth_sessions.py -q` and confirm it fails because expiry fields and policy still exist.
- [x] Remove `SessionPolicy`, time checks, and writes to `last_seen_at`/`absolute_expires_at`; retain revoked-session rejection and CSRF checking.
- [x] Add migration `0004` using Alembic batch operations to drop `last_seen_at` and `absolute_expires_at`, preserving every other session column.
- [x] Run the focused tests and a fresh `alembic upgrade head && alembic check`.
- [x] Commit with `git commit -m "feat(manager): keep owner sessions until logout"`.

### Task 2: Cookie and API contract

**Files:**
- Modify: `tests/manager/test_auth_api.py`
- Modify: `tests/manager/test_auth_contract.py`
- Modify: `manager_backend/auth/schemas.py`
- Modify: `manager_backend/auth/routes.py`
- Regenerate: `manager_backend/openapi.json`
- Modify: `docs/superpowers/specs/2026-07-21-windows-profile-manager-design.md`

**Interfaces:**
- Consumes: persistent `IssuedSession` and `ValidatedSession` from Task 1.
- Produces: `OwnerSessionRead` with only `email: EmailStr` and `csrf_token: str`.

- [x] Add failing assertions that session responses omit expiry metadata and cookies omit `Max-Age`/`Expires`.
- [x] Run focused API/contract tests and confirm the old response and cookie fail them.
- [x] Remove expiry fields from `OwnerSessionRead`, remove `max_age` from both cookies, and remove expiry calculations from routes.
- [x] Update the canonical manager design to state explicit-revocation lifetime and the reduced session response.
- [x] Regenerate OpenAPI with `python -m manager_backend.export_openapi`.
- [x] Run all manager tests and `git diff --check`.
- [x] Commit with `git commit -m "docs(manager): publish persistent session contract"` and push the feature branch.
