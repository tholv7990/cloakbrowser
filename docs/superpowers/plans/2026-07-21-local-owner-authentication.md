# Local Owner Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require one local owner to authenticate with email and password before accessing profile management.

**Architecture:** Owner credentials are local SQLite records with Argon2id password hashes. Login creates an opaque cookie token while the database stores only its SHA-256 hash and a separate hashed CSRF token. A FastAPI dependency validates session lifetime, inactivity, exact Origin, and CSRF before protected operations.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, argon2-cffi, Python `secrets`/`hashlib`, pytest.

## Global Constraints

- Exactly one local owner account; no roles, registration service, email delivery, or cloud dependency.
- Never store or log plaintext passwords, session tokens, or CSRF tokens.
- Session cookie is `HttpOnly`, `SameSite=Strict`, path `/`, and `Secure` when the configured frontend uses HTTPS.
- Only session-token and CSRF-token hashes are stored in SQLite.
- All protected mutations require `X-CSRF-Token` and exact configured Origin.
- Login failures use one generic response and increasing local delay after five failures.

### Task 1: Owner/session persistence and password service

**Files:**
- Modify: `pyproject.toml`
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0003_local_owner_auth.py`
- Create: `manager_backend/auth/passwords.py`
- Create: `manager_backend/auth/schemas.py`
- Test: `tests/manager/test_auth_passwords.py`

- [x] Write failing tests for email normalization, Argon2id verification, password minimum length, single-owner database enforcement, and absence of plaintext fields.
- [x] Run `python -m pytest -q tests/manager/test_auth_passwords.py` and confirm missing auth modules.
- [x] Add `argon2-cffi`, strict schemas, owner/session models, and migration `0003`.
- [x] Run auth tests and fresh/upgrade migration drift checks.
- [x] Commit with `git commit -m "feat(manager): add local owner credential storage"`.

### Task 2: Session creation and validation

**Files:**
- Create: `manager_backend/auth/sessions.py`
- Modify: `manager_backend/dependencies.py`
- Test: `tests/manager/test_auth_sessions.py`

- [ ] Write failing tests for opaque token hashing, idle/absolute expiry, revocation, exact Origin, CSRF validation, and sanitized errors.
- [ ] Run the tests and confirm missing session interfaces.
- [ ] Implement session issuance, constant-time hash comparison, expiry/revocation, and protected dependencies.
- [ ] Run session and existing security tests.
- [ ] Commit with `git commit -m "feat(manager): enforce local authenticated sessions"`.

### Task 3: Setup/login/logout/lock/password endpoints

**Files:**
- Create: `manager_backend/auth/routes.py`
- Modify: `manager_backend/api.py`
- Modify: `manager_backend/main.py`
- Test: `tests/manager/test_auth_api.py`

- [ ] Write failing API tests covering first setup, second setup rejection, generic login failure, successful cookie login, session lookup, logout, lock, and password change.
- [ ] Run tests and confirm missing routes.
- [ ] Implement the public auth router, protected router integration, cookies, CSRF handling, and login throttling.
- [ ] Run all manager API tests with authenticated fixtures.
- [ ] Commit with `git commit -m "feat(manager): add local email and password login"`.

### Task 4: OpenAPI/frontend handoff

**Files:**
- Modify: `manager_backend/openapi.json`
- Test: `tests/manager/test_auth_contract.py`

- [ ] Add contract tests ensuring protected routes declare cookie/CSRF security and auth responses never expose cookie tokens or password hashes.
- [ ] Export the canonical OpenAPI fixture.
- [ ] Run all manager tests and the fast CloakBrowser regression suite.
- [ ] Commit with `git commit -m "docs(manager): publish local authentication contract"`.
