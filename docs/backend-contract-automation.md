# Backend contract — Automation (recorder → template → multi-profile run)

**Owner:** backend (Codex). Frontend (nav item + record/run screens) built afterward by the frontend agent, same as the resource monitor.

**Reference implementation:** `Quantum-Source-Clean-*/backend/services/{browser_runtime,automation_service,automation_repository,profile_factory_service}.py`, `backend/api/automations.py`, `backend/v65_engine/core/launcher.py`, `frontend/src/pages/AutomationTemplates.tsx`. Read these for the exact algorithms — this doc adapts them to `manager_backend`.

## Goal

Record a flow inside a running profile browser, save it as a reusable **template**, then **replay** that template across N profiles in parallel — each with independent status and a "pause for human" gate (CAPTCHA/OTP/Cloudflare). Full scope: recorder, templates, multi-profile runs, credential pool, profile factory.

## Non-negotiables (our constraints)

- **No website credentials in the DB or templates.** `email`/`password` step values are stored as *variable references* (`{"variable": "email"}`), never literals. Actual pooled secrets go in the existing **secure credential store** (`features/proxies/credentials.py` `CredentialStore`), keyed by a ref; the DB holds only a SHA-256 fingerprint + status. Redact everything in API payloads. (Quantum stores them in SQLite masked; we do better — reuse `CredentialStore`.)
- **SQLAlchemy + Alembic**, not raw `sqlite3`. New tables via a migration in `manager_backend/migrations/versions/`. Keep the WAL/`busy_timeout` PRAGMAs already configured in `db.py`.
- **`StrictModel` (`extra="forbid"`)** schemas, `/api/v1` prefix, same session/origin auth dependency as other routers.
- Gate the whole feature behind a new capability flag **`automation`** in `features/app/routes.py` `AppCapabilities` (add `automation: bool`; frontend already reads capabilities and will nav-gate on it).

## Data model (new SQLAlchemy models + one Alembic migration)

- `automation_template` — `id`, `name`, `description`, `steps_json` (JSON), `created_at`, `updated_at`.
- `automation_recording` — `id`, `name`, `description`, `profile_id`, `status` (`recording|stopped|cancelled`), `step_count`, `created_at`.
- `automation_run` — `id`, `template_id`, `status` (`running|completed|failed|cancelled`), `max_parallel`, `total`, `completed_count`, `failed_count`, `attention_count`, `created_at`, `started_at`, `finished_at`.
- `automation_run_item` — `id`, `run_id`, `profile_id`, `status` (`pending|running|attention|completed|failed|cancelled`), `current_step`, `last_completed_step`, `message`, `attention_reason`, `error`, `screenshot_path`, `credential_ref` (nullable → secure store), `variables_json` (non-secret vars only).
- `automation_credential` — `id`, `fingerprint_sha256` (unique), `status` (`available|reserved|used|failed`), `reserved_run_id`, `reserved_profile_id`, `credential_ref` (→ secure store), `created_at`.
- `profile_factory_job` — `id`, `status`, `quantity`, `profile_template_id`, `automation_template_id` (nullable), `created_at`, plus progress counts.
- `profile_factory_item` — `id`, `job_id`, `profile_id` (nullable until created), `status`, `message`.

**Step JSON shape** (`steps_json`): ordered list, each `{type, ...}`:
- `goto`: `{type:"goto", url, url_pattern}`
- `click`: `{type:"click", selectors:[<strategy>...], success_url_pattern?}`
- `fill`: `{type:"fill", selectors:[...], value?|variable?}` (`variable` ∈ `email|password|<custom>`)
- `select`: `{type:"select", selectors:[...], value}`
- `wait_url`: `{type:"wait_url", url_pattern}`

A `<strategy>` is the rich descriptor `{css, id, name, role, accessible_name, placeholder, aria_label, text, testid}` — replay tries them in order (see §Mechanisms).

## HTTP surface (`features/automation/routes.py`, prefix `/api/v1/automations`)

Templates: `GET /templates`, `GET /templates/{id}`, `PUT /templates/{id}` (`{name, description, steps}`), `DELETE /templates/{id}`.
Recordings: `POST /recordings` (`{name, profile_id, description}`) → 202 recording; `GET /recordings/{id}` (poll `status`, `step_count`); `POST /recordings/{id}/stop` → new template; `POST /recordings/{id}/cancel`.
Runs: `POST /templates/{id}/runs` (`{assignments:[{profile_id, variables, credential_id?}], max_parallel}`) → 202 run; `GET /runs/{id}` (poll: run + items); `POST /runs/{id}/cancel`; `POST /runs/{id}/profiles/{profile_id}/continue`; `.../retry`; `.../mark-completed`.
Credentials: `GET /credentials` (pool summary counts only, **no secrets**); `POST /credentials/import` (`{text}` — `email:password` lines).
Factory: `GET /factory/jobs`, `POST /factory/jobs` (`{quantity, profile_template_id, automation_template_id?, start_automation}`), `GET /factory/jobs/{id}`, `POST /factory/jobs/{id}/cancel`.

Error mapping (mirror Quantum `automations.py:84`): unknown id → 404, validation → 400 (`ManagerError`), else 500.

## Realtime / status

Follow the resource-monitor decision: **poll, don't push.** The frontend polls `GET /runs/{id}` (~1s) and `GET /recordings/{id}` (~900ms) only while a run/record panel is open. No new WS event types needed. (Optionally emit a lightweight `automation.changed` ping on the existing `/events` WS to trigger a refetch, but polling-while-open is sufficient and simpler.)

## Backend mechanisms (the hard parts — port from Quantum)

1. **Cross-thread command controller** (`browser_runtime.py:336` + `v65_engine/core/launcher.py:746`). Playwright objects are thread-affine; runs are driven from a `ThreadPoolExecutor`. Build a per-profile `RuntimeController`: worker threads call `submit(action, payload) -> result` which enqueues a `RuntimeCommand` and blocks on a per-command `Event`; the profile's **single Playwright thread** drains the queue in a `tick()` loop and sets the Event. **Integration point for us:** our `features/runtime/worker.py` `ProfileWorker` already owns the launched `BrowserContext` on its own thread (`launcher.py` returns `_PersistentContextHandle`). Extend `ProfileWorker` to (a) hold a command queue, (b) run a `tick()` drain loop (wake on a pending-command Event with a ~100ms fallback poll), and (c) expose `controller_for(profile_id)`. This one piece unblocks recording *and* replay.
2. **Injected recorder script** (`browser_runtime.py:68-277`). On record start, `context.add_init_script(RECORDER_SCRIPT)` **and** `evaluate` it into every existing frame; seed the current URL as an initial `goto`. The script hangs **capture-phase** listeners on `click`/`submit`/`input`/`change`, buffers events on `window.__quantumRecorderEvents` (debounced input flush; traverse shadow DOM), and exposes drain/stop hooks. `tick()` drains events each cycle and synthesizes navigation steps by diffing frame URLs. Infer credential variables: an input whose type/name/autocomplete says email/password becomes a `{variable}` and its **value is never captured** (`browser_runtime.py:179,210`).
3. **Multi-strategy locator** (`browser_runtime.py:577-712`). Replay builds an *ordered* candidate list from the descriptor: form fields prefer stable `css`/`id`/`name`; clicks prefer `role`+`accessible_name`/`text`. Filter to a **visible/editable** match; if none yet, a lazy wait-fallback still gives the element its full timeout. This is why a generic submit button never mis-fires.
4. **URL-pattern synthesis** (`browser_runtime.py:516-545`). Wildcard dynamic path segments (UUIDs, long tokens, children of `store/session/account/...`) and keep only stable query keys, so one-time signup/session URLs re-match on replay. Attach the *next* `wait_for_url` as a click's `success_url_pattern`; the click executor retries until the URL settles (`browser_runtime.py:843`).
5. **Human-gate detection** (`browser_runtime.py:714-756`). Before each interactive step, a single `page.evaluate` heuristic fires only on a **visibly rendered** recaptcha/hcaptcha/turnstile/cloudflare iframe or an OTP field (`autocomplete="one-time-code"`, `name/id*="otp"`), returning a human-readable reason. On a gate: set item `status=attention`, `attention_reason=<reason>`, and **block on a per-profile `threading.Event`** until `.../continue` (or run cancel) releases it. Other profiles keep running.
6. **Run coordinator** (`automation_service.py:362-541`). Validate assignments (unique profiles, ≤50, required non-credential variables present unless a `credential_id` supplies them), **atomically reserve** pooled credentials (`UPDATE automation_credential SET status='reserved',... WHERE id=? AND status='available'`, rowcount==1 guard), persist the run, then `ThreadPoolExecutor(max_workers=clamp(max_parallel,1,5))` one `_run_profile` future each. `_run_profile`: open profile → `controller.wait_ready()` → iterate steps from `start_step`; on success save/complete the credential; on failure screenshot + redacted error; `finally` release the credential if not completed. Recompute aggregate counts after each item.
7. **Credential pool** (`automation_repository.py:478-642`). Import → SHA-256 fingerprint (dedupe) → secret to `CredentialStore`, row holds ref+status. Reserve/complete/release keyed by `(reserved_run_id, reserved_profile_id)`. `GET /credentials` returns counts only.
8. **Resumability + recovery.** Each item tracks `last_completed_step`; `retry` re-runs a 1-profile run from that checkpoint; `mark-completed` finalizes a false-negative and completes its credential. On app **startup (lifespan)**, mark interrupted `running` runs/items as failed and release their reserved credentials (mirror `automation_service.py:77`).
9. **Profile factory** (`profile_factory_service.py:52-463`). Validate (1–50; requires a profile/fingerprint template; if `start_automation`, the automation must declare `email`+`password` vars and the pool must hold ≥quantity available). Worker: generate proxies (reuse our proxy layer / providers) → per-item health-check with up to 3 replacements → `create_profile` from the fingerprint template → assign proxy → tag; then `start_automation_run` with one credential per item and poll to terminal, tagging outcomes. Cancellation cascades into run cancel.

## Reuse our stealth cleanly

Thread a per-call **humanize preset** into the Playwright actions (Quantum's `AUTOMATION_HUMAN_CONFIG`, `browser_runtime.py:17`). We already have humanized mouse/keyboard in `cloakbrowser` (`human/`); replay's click/fill/select should route through it (or pass `humanize`/preset kwargs) so automated actions keep the same behavioral fingerprint as manual use — skip the redundant second actionability wait (Quantum uses `force=True` after one visibility check to avoid ~1-minute stalls).

## Frontend (built afterward by the frontend agent)

New **Automation** nav item + screen, gated by the `automation` capability. Record modal (pick profile → live `step_count` → stop→save template), template list/editor, run wizard (select profiles + assign variables/credentials + `max_parallel`), live run view (per-profile status + Continue/Retry/Mark-completed), credential-pool import, factory wizard. Polls `GET /runs/{id}` / `GET /recordings/{id}` while open. Full EN/VI. — Not Codex's job; listed so the contract is understood end-to-end.

## Suggested build order

1. `RuntimeController` command-queue + `tick()` integration into `ProfileWorker` (unblocks everything).
2. Recorder script → `stop` → template persistence.
3. Single-profile replay (locator + URL-pattern + step executor).
4. Multi-profile runs + human-gate Events + status/counts + cancel.
5. Credential pool (secure store) + reserve/release + startup recovery.
6. Profile factory.

## Tests

`tests/manager/test_automation_*.py`: template CRUD; recording lifecycle (mock the controller); run validation (dupes/limit/missing-vars); credential reserve is atomic (no double-reserve under concurrency); human-gate blocks then `continue` resumes; retry resumes from `last_completed_step`; startup recovery releases reserved creds. Update `openapi.json` if the export is checked in.
