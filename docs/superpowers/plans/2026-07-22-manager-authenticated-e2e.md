# Manager Authenticated E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and execute a redacted Windows authenticated smoke suite across the completed Manager foundation.

**Architecture:** A pytest live harness starts isolated backend/frontend processes, uses API and browser adapters, tracks only suite-owned resources, and writes redacted reports. Deterministic mode uses a temporary data root; existing-owner mode reads credentials only from environment.

**Tech Stack:** pytest, subprocess, FastAPI/Uvicorn, Vite, Playwright/CloakBrowser, JSON/Markdown reports.

## Global Constraints

- Read credentials only from `CLOAK_MANAGER_EMAIL` and `CLOAK_MANAGER_PASSWORD`.
- Never log or report passwords, cookies, license/CSRF/session values, proxy credentials, or user profile data.
- Cleanup only exact suite-owned IDs/paths after resolved containment checks.
- Public diagnostics require `CLOAK_LIVE_DIAGNOSTICS=1`; CAPTCHA is never solved.

---

### Task 1: Redacted E2E harness

**Files:**
- Create: `tests/manager/e2e/conftest.py`
- Create: `tests/manager/e2e/reporting.py`
- Create: `tests/manager/e2e/test_manager_smoke.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces fixtures `manager_stack`, `authenticated_client`, `disposable_profile`, and `e2e_report`.

- [ ] Write failing unit tests for environment-only credentials, port readiness, resource tracking, exact cleanup, and recursive report redaction.
- [ ] Run `python -m pytest tests/manager/e2e -q`; confirm missing fixtures/modules.
- [ ] Implement hidden Windows subprocess startup, condition-based readiness, temporary Manager data root, authenticated session/CSRF client, and JSON/Markdown redactor.
- [ ] Run harness unit tests and confirm green.
- [ ] Commit with `git commit -m "test(manager): add authenticated e2e harness"`.

### Task 2: Deterministic full smoke scenario

**Files:**
- Modify: `tests/manager/e2e/test_manager_smoke.py`
- Add: `tests/fixtures/extensions/manager-e2e/manifest.json`
- Add: `tests/fixtures/cookies/manager-e2e.json`

- [ ] Write the ordered scenario assertions from the approved E2E spec: login, create, partial edit, extension, cookie round-trip, launch/count/logs, stop, export/import identity change, local diagnostics, directory containment, cleanup.
- [ ] Run it against the temporary data root and confirm the first unsupported contract fails.
- [ ] Complete only harness glue needed by the shipped APIs; do not weaken assertions.
- [ ] Re-run and require all scenario steps and cleanup status pass.
- [ ] Commit with `git commit -m "test(manager): cover full foundation smoke flow"`.

### Task 3: Existing-owner and optional live validation

**Files:**
- Create: `scripts/run_manager_e2e.ps1`
- Modify: `tests/manager/e2e/test_manager_smoke.py`
- Modify: `.gitignore`

- [ ] Add tests that skip with exact missing-variable reasons and never print values.
- [ ] Implement the script to set no secrets itself, invoke pytest with existing process environment, and place reports under ignored `artifacts/manager-e2e/`.
- [ ] Run deterministic mode. Run existing-owner mode only when both Manager credentials are supplied; run public diagnostics only with the explicit flag.
- [ ] Commit with `git commit -m "test(manager): add existing-owner smoke runner"`.

### Task 4: Final release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/CODEBASE_FUNCTIONALITY.md`
- Modify: `docs/frontend-backend-contract-questions.md`

- [ ] Run `python -m pytest tests/manager -q` and the deterministic E2E suite.
- [ ] Run `npm test -- --run`, `npm run typecheck`, `npm run build`, and formatting checks in `manager/frontend`.
- [ ] Regenerate OpenAPI and fail on diff; scan tracked files for license/password/token-shaped secrets; run `git diff --check`.
- [ ] Update documentation with exact completed capabilities, limitations, commands, and environment variable names without values.
- [ ] Commit with `git commit -m "docs(manager): complete foundation milestone"` and push only after verifying clean status and remote divergence.
