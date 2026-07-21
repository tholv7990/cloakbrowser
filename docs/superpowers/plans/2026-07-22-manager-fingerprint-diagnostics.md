# Manager Fingerprint Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persisted asynchronous Pixelscan, IPhey, Cloudflare, Google Search, and direct-control diagnostics with safe reports and CAPTCHA pause behavior.

**Architecture:** A diagnostics manager owns bounded concurrency, lifecycle, cancellation, persistence, events, and injected target runners. Runners reuse the normal profile launch builder and extract only allowlisted visible findings into manager-owned artifacts.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, asyncio, Playwright through CloakBrowser, React/TypeScript.

## Global Constraints

- Diagnostics are observations, not guarantees or automatic fingerprint modifications.
- One active run per profile; CAPTCHAs are reported and never solved automatically.
- Only allowlisted HTTPS public targets; deterministic automated tests use local fixtures through injected adapters.
- Never persist raw DOM, storage, cookies, response bodies, credentials, or arbitrary exception text.

---

### Task 1: Diagnostic persistence and API lifecycle

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0010_diagnostics.py`
- Create: `manager_backend/features/diagnostics/schemas.py`
- Create: `manager_backend/features/diagnostics/service.py`
- Create: `manager_backend/features/diagnostics/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_diagnostics_api.py`

**Interfaces:**
- Produces: `DiagnosticManager.create(kind, profile_id)`, `.cancel(id)`, `.recover_orphans()` and list/get/create/cancel routes.

- [ ] Write failing tests for every kind/status, pagination filters, HTTP 202, per-profile conflict, cancellation, and orphan recovery.
- [ ] Run tests and confirm missing routes/models.
- [ ] Add model/migration, strict schemas, bounded progress, one-active-run query, safe state transitions, and startup recovery.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): persist diagnostic runs"`.

### Task 2: Safe runner boundary and artifacts

**Files:**
- Create: `manager_backend/features/diagnostics/runner.py`
- Create: `manager_backend/features/diagnostics/artifacts.py`
- Modify: `manager_backend/config.py`
- Test: `tests/manager/test_diagnostic_runner.py`

**Interfaces:**
- Produces: `DiagnosticRunner.run(request, cancel_event, progress) -> DiagnosticResult`; `write_diagnostic_artifacts(...)`.

- [ ] Write failing tests for stopped-state requirement, direct temporary profile, profile launch reuse, proxy preflight failure, URL allowlist, timeout/crash mapping, artifact containment, cleanup, and cancellation.
- [ ] Run focused tests and verify absence.
- [ ] Implement injected browser/target adapters, concurrency semaphore, safe error map, JSON report and screenshot paths under exact run root, and `finally` cleanup.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): add safe diagnostic runner"`.

### Task 3: Target-specific normalization and CAPTCHA handling

**Files:**
- Create: `manager_backend/features/diagnostics/targets.py`
- Test: `tests/manager/test_diagnostic_targets.py`
- Add fixtures: `tests/fixtures/diagnostics/*.html`

**Interfaces:**
- Produces: `normalize_pixelscan`, `normalize_iphey`, `normalize_cloudflare`, and `normalize_google_search` returning bounded findings and final status.

- [ ] Write fixture-driven failing tests for pass/warning/failure, layout-change warning, consent/interstitial, unusual traffic, managed challenge, result visibility, and `captcha_user_action_required`.
- [ ] Run focused tests and confirm missing functions.
- [ ] Implement allowlisted selector/text extraction with strict output keys and sizes; CAPTCHA always returns warning and halts interaction.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): normalize fingerprint diagnostic targets"`.

### Task 4: Background execution and realtime events

**Files:**
- Modify: `manager_backend/features/diagnostics/service.py`
- Modify: `manager_backend/main.py`
- Modify: `manager_backend/events.py`
- Test: `tests/manager/test_diagnostics_api.py`

**Interfaces:**
- Produces: WebSocket `diagnostic.progress` and `diagnostic.completed` envelopes.

- [ ] Add failing tests for queued→running→terminal transitions, 0–100 progress, cancellation cleanup, safe event payloads, shutdown, and startup recovery.
- [ ] Run tests and verify failures.
- [ ] Initialize manager in app lifespan, schedule owned tasks, publish bounded events, cancel/await tasks during shutdown.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): run diagnostics asynchronously"`.

### Task 5: Real Diagnostics frontend

**Files:**
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/types/events.ts`
- Modify: `manager/frontend/src/api/realApi.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Modify: `manager/frontend/src/features/diagnostics/DiagnosticsPage.tsx`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`
- Test: `manager/frontend/src/features/diagnostics/DiagnosticsPage.test.tsx`

- [ ] Write failing tests for selectors, queued/running progress, history filters, direct/profile distinction, timestamp, safe errors, CAPTCHA action-required copy, cancellation, and artifact links.
- [ ] Run frontend tests and confirm failures.
- [ ] Wire real API/realtime updates and accessible result cards; retain mock schema compatibility.
- [ ] Run tests, typecheck, and build.
- [ ] Commit with `git commit -m "feat(manager-frontend): wire fingerprint diagnostics"`.

### Task 6: Live test harness and contract gate

**Files:**
- Create: `tests/manager/test_diagnostics_live.py`
- Modify: `manager_backend/openapi.json`
- Modify: `docs/frontend-backend-contract-questions.md`

- [ ] Add tests marked `live` and skipped unless `CLOAK_LIVE_DIAGNOSTICS=1`; no CAPTCHA interaction.
- [ ] Regenerate OpenAPI and run deterministic backend/frontend gates.
- [ ] Commit with `git commit -m "test(manager): add optional live diagnostic checks"`.
