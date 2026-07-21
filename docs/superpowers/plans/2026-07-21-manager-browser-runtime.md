# Manager Browser Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace profile runtime placeholders with an owned, queued, persistent browser lifecycle and authenticated runtime events.

**Architecture:** A central `RuntimeManager` coordinates per-profile `ProfileWorker` threads. Each worker creates and controls its Playwright persistent context on one thread; SQLAlchemy runtime rows and a small event broker expose authoritative state without placing Playwright objects in FastAPI request threads.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Playwright/CloakBrowser persistent contexts, psutil, filelock, WebSockets, pytest.

## Global Constraints

- One active runtime per profile.
- Maximum concurrent launches defaults to 2 and is configurable from 1 to 8.
- Never expose commands, local paths, credentials, authenticated URLs, or raw exceptions.
- Never terminate a PID without matching PID, creation time, command line, and manager-owned profile directory.
- Offline manager tests use fake launchers/process inspectors and launch no browser.

### Task 1: Runtime persistence and state service

**Files:** Modify `manager_backend/models.py`, profile service/schemas; create migration `0005_runtime_sessions.py`, `manager_backend/features/runtime/{schemas.py,service.py}`, and persistence/migration tests.

- [ ] Write failing tests asserting runtime state comes from an active session, invalid transitions fail, trashed profiles cannot start, and only one active session exists per profile.
- [ ] Add `RuntimeSession` with queued/starting/running/stopping/stopped/crashed/detached states and a SQLite partial unique index for active profile states.
- [ ] Implement safe transition helpers and runtime serialization; replace constant profile `runtime_state`.
- [ ] Run state and migration upgrade/downgrade tests; commit `feat(manager): persist owned profile runtime state`.

### Task 2: Worker ownership, locks, and launch queue

**Files:** Create `manager_backend/features/runtime/{manager.py,worker.py,launcher.py,locks.py}`, modify settings/main, and add worker/manager tests.

- [ ] Write failing tests for two-launch concurrency, queued third launch, duplicate start rejection, same-thread launch/close, filesystem-lock failure, partial cleanup, idempotent stop, crash transition, and shutdown.
- [ ] Define injected `BrowserLauncher.run(snapshot, commands, callbacks)` and implement `FakeBrowserLauncher` tests before production launcher.
- [ ] Implement `RuntimeManager`, profile locks, launch semaphore, worker command queues, safe callbacks, and configurable `max_concurrent_launches`.
- [ ] Implement `CloakPersistentLauncher` using the manager-owned data directory, stable seed, consistent preset, allowlisted arguments, startup URLs, and headed persistent context.
- [ ] Run offline runtime tests and focused existing browser/session tests; commit `feat(manager): own profile browser workers`.

### Task 3: REST and WebSocket contract

**Files:** Create runtime routes/events, replace profile start/stop placeholders, modify API/main/OpenAPI, and add authenticated API/WebSocket tests.

- [ ] Write failing tests for start HTTP 202, duplicate start, stop/idempotency, runtime detail/list, profile-list state, cookie-authenticated events, foreign/missing Origin rejection, monotonic sequence, and secret-free messages.
- [ ] Implement REST routes over `RuntimeManager` and `/api/v1/events` WebSocket using session-cookie validation plus exact Origin.
- [ ] Keep focus-window as typed `runtime_command_not_supported` until Windows focus support is implemented.
- [ ] Run API/security/event tests and regenerate OpenAPI; commit `feat(manager): expose owned browser runtime`.

### Task 4: Reconciliation and verification

**Files:** Create `manager_backend/features/runtime/reconcile.py`, modify app lifespan/README/canonical design, and add reconciliation/contract tests.

- [ ] Write failing tests for dead-owner crash marking, verified CDP reconnect attempt, unsafe live process detached state, stale-lock verification, and reconciliation summary events.
- [ ] Implement injected process/CDP inspection, startup reconciliation, and graceful shutdown through FastAPI lifespan.
- [ ] Add contract tests for runtime schemas/capability flag and create a slow Windows real-browser lifecycle test.
- [ ] Run all manager tests, relevant browser/session regressions, migration drift, and optional slow test when the binary is available.
- [ ] Commit `docs(manager): publish browser runtime contract`, push the feature branch, merge through a clean integration worktree, verify, and push main.
