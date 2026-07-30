# Shop-check Provisioning + Run Coordinator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn a queued Shop-check run into launched, owned temporary profiles — allocate workers, generate+preflight one 711 proxy per profile, create a uniquely-seeded profile, persist immutable ownership, and drive it all on a bounded, restart-safe coordinator — **without** implementing browser-page automation (email entry/classification is a later checkpoint).

**Architecture:** A `provisioner` builds worker groups and provisions each worker's proxy→profile→ownership in a compensating sequence. A `coordinator` (mirroring the proven `features/automation/coordinator.py`) owns a bounded `ThreadPoolExecutor`, one DB session per worker, atomic status-guarded claims, cancellation, startup recovery, and count recomputation. The actual per-email page work is an **injected callback** (`process_worker`), faked in every test this checkpoint; the real browser adapter arrives later. Browser launch is abstracted behind a `RuntimeLauncher` protocol (wrapping `RuntimeManager`), faked in unit tests.

**Tech Stack:** Python 3.13, SQLAlchemy 2 + Alembic (SQLite/WAL), FastAPI, `concurrent.futures.ThreadPoolExecutor`, existing `features/proxies` provider layer, existing `features/profiles/service.create_profile`, existing `CredentialStore`.

## Global Constraints (verbatim, apply to every task)

- Do **not** implement browser-page automation (no shop.app navigation, no email entry, no classification) this checkpoint.
- Do **not** edit published migrations `0017`; `0018`/`0019` may gain columns only via a **new** migration `0020` if schema changes are needed (never edit `0018`/`0019` retroactively once this checkpoint is reviewed — but they are unreleased now, so a new `0020` is still the chosen path for additive fields to keep history append-only).
- Full email lives **only** in `CredentialStore`; DB stores fingerprint + `credential_ref` + masked value. Never put an email/proxy secret in DB, logs, exceptions, metrics, or API responses.
- Every persisted error goes through `service.set_run_error` / `set_worker_error` / `set_email_error` (which call `sanitize.sanitize_error`).
- Reuse `features/proxies` provider infra (`generate_and_store` / `DefaultProviderClient`) — no parallel proxy implementation. Never log an authenticated proxy URL.
- One SQLAlchemy session per worker thread; never share a session across threads. Aggregate counts recomputed from `shop_check_emails` rows (never incremented optimistically).
- `max_parallel` clamped 1–5; workload target: ≤1000 emails, 5/profile, ≤200 profiles.
- No browser/network in ordinary unit tests (inject fakes). TDD: failing test before code; frequent commits.
- `emails_per_profile` and `max_parallel` come from the persisted run row (already validated 1–5 at create).

---

## File Structure

| File | Responsibility | New/Modify |
|---|---|---|
| `manager_backend/features/shop_check/provisioner.py` | Pure provisioning: group emails→workers; per-worker proxy(gen+preflight)→profile→ownership with compensation. No threads. | Create |
| `manager_backend/features/shop_check/launcher.py` | `RuntimeLauncher` protocol + `RuntimeManagerLauncher` (wraps `RuntimeManager.start/stop`); `FakeLauncher` lives in tests. | Create |
| `manager_backend/features/shop_check/coordinator.py` | `ShopCheckCoordinator`: bounded executor, per-worker sessions, state transitions, atomic claims, cancel, recovery, recompute. Injected `provisioner` + `process_worker`. | Create |
| `manager_backend/features/shop_check/service.py` | Add worker-grouping helper, worker/email read serialization already present; add `mark_worker_state`, ownership resolver for cleanup reuse. | Modify |
| `manager_backend/features/shop_check/routes.py` | `POST /runs` kicks off coordinator after create; keep response contract. | Modify |
| `manager_backend/main.py` | Build `ShopCheckCoordinator` in `create_app`; wire `recover_interrupted_runs` + coordinator `shutdown()` in lifespan (next to automation). | Modify |
| `manager_backend/migrations/versions/0020_shop_check_provisioning.py` | Additive columns only if needed (see "Schema deltas"). | Create (maybe) |
| `manager_backend/models.py` | Additive worker/run columns if `0020` is needed. | Modify (maybe) |
| `tests/manager/test_shop_check_grouping.py` | Worker grouping: 0/1/5/6/999/1000. | Create |
| `tests/manager/test_shop_check_provisioner.py` | Proxy gen/preflight, profile create, ownership, per-step compensation, provider failure taxonomy, sentinel leak. | Create |
| `tests/manager/test_shop_check_coordinator.py` | Concurrency claim, duplicate start, cancel at each phase, recovery races, recompute, no-secret-leak, SQLite lock contention. | Create |

### Schema deltas (decide in Task 0)
The current models already carry everything needed **except** possibly:
- A **provenance stamp** proving a profile belongs to this run beyond the `shop_check_workers.profile_id` row. Decision (Task 0): the immutable `shop_check_workers(run_id, profile_id)` row **is** the authoritative provenance (already globally-unique + immutability trigger); cleanup resolves owned profile ids from it. **No new profile column, no name prefix.** → **No `0020` needed** unless we add `run.prepared_at`/`worker.launched_at` timestamps for observability. Plan assumes **no `0020`** and notes it as an unresolved decision.

---

## State-transition tables

### Run (`shop_check_runs.status`)
| From | Event | To | Guard |
|---|---|---|---|
| queued | coordinator starts | preparing | atomic `UPDATE ... WHERE status='queued'` (claims the run) |
| preparing | first worker launched / processing begins | running | any worker left `launching` |
| running | all emails terminal, none retryable | completed | recomputed from rows |
| running | all emails terminal, ≥1 retryable/issue | completed_with_issues | recomputed |
| queued/preparing/running | cancel requested | cancelled | cancel token set; non-terminal emails → `cancelled` |
| preparing/running | unrecoverable coordinator error | failed | sanitized `run.error` |
| queued/preparing/running | startup recovery (interrupted) | failed | recovery marks interrupted runs failed (mirrors automation) |

### Worker (`shop_check_workers.state`)
`pending → proxy_check → profile_create → launching → processing → stopping → terminal`
| From | Event | To |
|---|---|---|
| pending | claim worker (atomic) | proxy_check |
| proxy_check | proxy generated + preflight OK | profile_create |
| proxy_check | proxy failure after bounded retries | terminal (worker.error sanitized; its emails → `proxy_failed`) |
| profile_create | profile created + ownership committed | launching |
| launching | browser launched (injected launcher) | processing |
| processing | `process_worker` returns (this checkpoint: fake completes) | stopping |
| stopping | runtime stopped | terminal |
| any | cancel | stopping → terminal (emails per §Cancellation) |

### Email (`shop_check_emails.state` / `result`)
`pending → running → terminal(result)` — **result assignment is out of scope this checkpoint** except:
- worker proxy failure → its still-`pending` emails become `terminal/proxy_failed` (retryable).
- cancel → still-non-terminal emails become `terminal/cancelled`.
- Normal per-email classification (`phone_otp_required`, …) is the later browser checkpoint.

---

## Transaction boundaries (SQLite; keep write txns short, no network inside an open write txn)

1. **Claim run:** `UPDATE shop_check_runs SET status='preparing', started_at=? WHERE id=? AND status='queued'` → rowcount==1 guard. Own txn, instant.
2. **Create workers (grouping):** one txn inserts all worker rows (`state='pending'`, ordinal k, assigned_count) and sets `shop_check_emails.worker_id` by ordinal range. Idempotent via `uq_shop_check_workers_run_ordinal`. Instant, no network.
3. **Proxy generation:** `generate_and_store(count=1)` runs the **network call before** its own commit; called on a **fresh short-lived session**, not inside any other open txn. Produces a pool `Proxy` row + `credential_ref` in store.
4. **Proxy preflight:** network (`ScannerQuickTester.run_fast`) with **no DB txn open**; result cached on the `Proxy` row in a short txn.
5. **Profile create:** `create_profile(session, ProfileCreate(...))` — its own commit (unique seed, startup_urls=[target], proxy_id=generated). Instant.
6. **Ownership persist:** `UPDATE shop_check_workers SET profile_id=?, proxy_id=?, state='profile_create'→'launching' WHERE id=? AND profile_id IS NULL` → rowcount==1 (idempotent; immutability trigger is backstop). Instant.
7. **Launch:** injected `launcher.start(profile_id)` — **no DB write txn held during launch**; state flips to `launching`/`processing` in short txns around it.
8. **Recompute:** `service.recompute_run` in its own short txn after each worker terminal transition.

**Never**: hold a write txn across steps 3/4/7 (network/browser). **Never**: `generate_and_store` inside the worker-grouping txn.

---

## Idempotency strategy

- **Run claim** is the single idempotency gate: only the `UPDATE ... WHERE status='queued'` winner proceeds; a duplicate coordinator start finds rowcount 0 and no-ops.
- **Workers** are keyed by `uq_shop_check_workers_run_ordinal`; grouping uses `INSERT` that a second run swallows (worker already exists → SELECT it). Grouping is a pure function of `(sorted valid emails, emails_per_profile)`, so re-running yields identical ordinals.
- **Ownership** write is guarded `WHERE profile_id IS NULL`; a retry that already assigned is a no-op; the immutability trigger blocks any change.
- **Proxy/profile creation after restart**: a worker in `profile_create`+ with `profile_id` already set skips creation; a worker in `proxy_check` with a `proxy_id` already set skips generation. State + the `profile_id`/`proxy_id` columns are the resume checkpoints, so restart never double-creates.
- **Credential journal** (already built) covers proxy-secret orphans from partial provisioning.

## Recovery strategy (startup, mirrors `automation.recover_interrupted_runs`)

- `recover_interrupted_runs(session_factory)`:
  1. Any run in `preparing`/`running` with no live coordinator worker → mark interrupted workers back to a resumable state OR fail the run per policy. **Policy (Task 0 decision):** mark interrupted `running` runs `failed` and their non-terminal emails retryable-`unknown`? No — prefer **resume**: leave rows, re-enqueue workers whose state ∉ terminal. Chosen: **resume-safe** — recovery re-submits any non-terminal worker to the coordinator; the idempotent claims prevent double work.
  2. Reconcile owned runtimes: stop any runtime owned by this run that the OS still shows (reuse `RuntimeManager`/reconcile) so a crashed run's browser doesn't linger.
  3. `reconcile_orphan_credentials` (already wired) cleans proxy-secret orphans.
- **Race guard:** recovery claims each worker with an atomic status-guarded `UPDATE` before submitting; a still-running worker holds its claim, so recovery's submit is a no-op (rowcount 0).

---

## Compensation matrix (partial-failure → action; profiles always remain discoverable + cleanable)

| Step that succeeded | Next step fails / crash / cancel | Compensation | Discoverable? |
|---|---|---|---|
| worker row committed | profile creation fails | worker → `terminal`, `worker.error` sanitized; its emails → `proxy_failed`(retryable). No profile exists. | n/a (no profile) |
| proxy generated (pool Proxy + secret) | profile update/create fails | Proxy row + secret **kept** (design: preserve proxy records); worker → terminal; retry reuses or regenerates. Credential journal already protects the secret. | proxy in pool |
| profile created | ownership persistence fails | Ownership `UPDATE` is the SAME txn as `state→launching`; if it fails, profile exists but no `shop_check_workers.profile_id`. **Recovery sweep**: a profile created by a run but not yet owned is found via the credential journal / a `pending_profile` marker (Task 0 decision below). | see "orphan profile" |
| proxy created | profile update fails | as above; proxy preserved. | proxy in pool |
| proxy test fails | — | bounded retry with a **new** session directive (regenerate); after N retries worker → terminal, emails → `proxy_failed`. | n/a |
| browser launch fails | — | worker → terminal, `worker.error` sanitized; profile **kept** and owned (cleanable); emails → retryable. | owned profile |
| crash at any boundary | restart | idempotent claims + `profile_id`/`proxy_id` checkpoints resume; `recover_interrupted_runs` re-enqueues non-terminal workers; orphan credentials reconciled. | owned profile / journal |
| cancel before provisioning | — | worker never claimed; emails → `cancelled`. | n/a |
| cancel during proxy test | — | abort retry loop; worker → terminal; emails → `cancelled`; any generated proxy preserved. | proxy in pool |
| cancel during launch | — | stop launch; if profile created, it stays owned+cleanable; emails → `cancelled`. | owned profile |
| cancel between emails | — | stop worker; owned profile stays; remaining emails → `cancelled`. | owned profile |

**Orphan profile (created but ownership not yet committed) — Task 0 decision:** persist ownership in the SAME transaction that flips the profile into existence is impossible (`create_profile` commits itself). Two options: **(A)** write a `shop_check_workers.profile_id` *intent* row (a `pending_profile_id` column via `0020`) BEFORE calling `create_profile`, using a deterministic profile id we pass into `create_profile`; then ownership is durable before the profile exists, and a crash leaves a resolvable intent. **(B)** accept a tiny window and add a recovery sweep that matches profiles with `startup_urls==[target]` created after `run.started_at` with no owning worker — rejected (uses heuristic, not provenance). **Plan chooses (A)**: pre-generate `profile_id` (uuid), write it to `shop_check_workers.profile_id` **before** `create_profile(id=profile_id)`, so provenance is durable first and creation is idempotent (`create_profile` with an existing id is a no-op/looked-up). This needs `create_profile` to accept a caller-supplied id — verify; if not, add a thin `create_owned_profile(session, profile_id, payload)` in profiles service (minimal, reused). **This is the one place a small shared-service change may be justified; flagged as unresolved.**

---

## Test matrix (deterministic; fakes only; no browser/network)

| Area | Test | Asserts |
|---|---|---|
| Grouping | 0/1/5/6/999/1000 emails × per=1..5 | worker_count == ceil(valid/per); ordinals 0..k-1; assigned_count sums to valid; email.worker_id ranges correct |
| Grouping idempotency | run grouping twice | no duplicate workers; identical ordinals |
| Provisioner | proxy gen success | one `Proxy` pool row, `proxy_id` on worker, secret in store, no secret in DB row |
| Provisioner | preflight failure → bounded retry | regenerates with new session; after N retries worker terminal, emails `proxy_failed` |
| Provisioner | provider taxonomy | distinct ManagerError codes: `proxy_provider_not_configured`, credential-missing, generation-failure, preflight-failure, timeout |
| Provisioner | profile created, ownership write fails | provisioner compensates; profile discoverable via provenance; retry idempotent |
| Ownership | immutability | second ownership write to a different profile aborts (trigger) |
| Coordinator | max_parallel honored | never > N concurrent worker claims (counter/semaphore probe) |
| Coordinator | concurrent claim attempts | exactly one claim wins per worker (atomic UPDATE) |
| Coordinator | duplicate coordinator start | second start no-ops (run already `preparing`) |
| Coordinator | cancel before/proxy/launch/between | emails end `cancelled`; owned profiles preserved; no orphan work |
| Recovery | restart after each boundary (worker/proxy/profile/ownership/launch) | resumes without duplicate profile/proxy; counts correct |
| Recovery race | recovery runs while a worker still runs | recovery submit no-ops; no double-processing |
| Counts | recompute from rows under overlap | totals == row truth; no double count |
| Security | end-to-end sentinel | inject sentinel email + proxy secret into a forced failure; assert absent from run/worker API JSON, `worker.error`, logs |
| Performance | SQLite lock contention | N workers commit concurrently without `database is locked` (WAL + busy_timeout); no write txn held across fake network |
| Isolation | no browser/network | fakes only; assert launcher/provider fakes used |

---

## Tasks (bite-sized, TDD)

### Task 0: Decisions + scaffolding
- [ ] Confirm `create_profile` can accept a caller-supplied `id` (read `profiles/service.py`); if not, plan `create_owned_profile(session, profile_id, payload)`.
- [ ] Confirm no `0020` needed (ownership = `shop_check_workers` row). Record decision in the plan's "unresolved" section; if timestamps/`pending` marker wanted, write `0020` additive-only.
- [ ] No code commit; this is a decision gate.

### Task 1: Worker grouping (`provisioner.group_workers`)
- **Files:** Create `provisioner.py`; Test `test_shop_check_grouping.py`.
- **Produces:** `group_workers(session, run_id) -> list[WorkerGroup]` where `WorkerGroup(ordinal:int, email_ids:list[str])`; persists `ShopCheckWorker` rows (`state='pending'`, `assigned_count`) and sets `email.worker_id`; sets `run.worker_count` from committed rows.
- [ ] Step 1: failing tests for 0/1/5/6/999/1000 × per∈{1,3,5}: assert worker_count, ordinals, assigned_count, email.worker_id ranges, and idempotency (run twice).
- [ ] Step 2: run → fail (function missing).
- [ ] Step 3: implement pure grouping + idempotent insert (guard on `uq_shop_check_workers_run_ordinal`; select-existing on conflict).
- [ ] Step 4: run → pass. Step 5: commit.

### Task 2: Proxy provisioning per worker (`provisioner.provision_proxy`)
- **Files:** `provisioner.py`; Test `test_shop_check_provisioner.py`.
- **Consumes:** `features/proxies/providers.generate_and_store` (count=1, provider='seveneleven', country=run.region or '', session_type sticky), `build_proxy_preflight`.
- **Produces:** `provision_proxy(session_factory, store, provider_client, tester, *, region, cancel) -> ProxyProvisionResult(proxy_id, exit_ip)`; bounded retries; typed failures.
- [ ] Step 1: failing tests — success creates one Proxy + secret-in-store (not DB); preflight-fail retries then raises typed error; each provider failure mode maps to a distinct code; cancel aborts retry loop; sentinel proxy secret never in any persisted error.
- [ ] Step 2–4: implement using a **fresh session** for `generate_and_store` (network before commit), preflight with no open txn, bounded retry with new session directive. Step 5: commit.

### Task 3: Profile create + durable ownership (`provisioner.provision_profile`)
- **Files:** `provisioner.py` (+ maybe `profiles/service.create_owned_profile`); Test `test_shop_check_provisioner.py`.
- **Produces:** `provision_profile(session, worker_id, *, profile_id, proxy_id, target_url, seed?) -> None`: writes `shop_check_workers.profile_id` intent FIRST, then `create_profile(id=profile_id, startup_urls=[target], proxy_id=proxy_id, unique seed)`, then flips `state→launching`. Idempotent.
- [ ] Step 1: failing tests — ownership durable before profile exists; profile created with unique seed + startup url + proxy; ownership write is `WHERE profile_id IS NULL`; second call no-ops; immutability trigger blocks re-point; profile discoverable via provenance after a simulated crash between ownership-intent and create.
- [ ] Step 2–4: implement. Step 5: commit.

### Task 4: RuntimeLauncher abstraction (`launcher.py`)
- **Files:** Create `launcher.py`; Test uses `FakeLauncher`.
- **Produces:** `class RuntimeLauncher(Protocol): def start(profile_id)->None; def stop(profile_id)->None`; `RuntimeManagerLauncher(runtime_manager)` delegating to `RuntimeManager.start/stop`. Tests inject `FakeLauncher`.
- [ ] Step 1–5: trivial protocol + delegate; test the delegate calls through with a fake `RuntimeManager`. Commit.

### Task 5: Coordinator skeleton (`coordinator.py`) — claim, sessions, executor, recompute
- **Files:** Create `coordinator.py`; Test `test_shop_check_coordinator.py`.
- **Consumes:** provisioner, launcher, `service.recompute_run`, `set_worker_error`.
- **Produces:** `ShopCheckCoordinator(session_factory, store, provider_client, tester, launcher, process_worker)`; `.start(session, run_id)` (atomic run claim → group → submit workers on `ThreadPoolExecutor(max_workers=clamp(max_parallel))`); `._run_worker(run_id, worker_id)` opens its OWN session; `.shutdown(timeout)`; `.cancel(session, run_id)`.
- [ ] Step 1: failing tests — start claims run once (duplicate start no-ops); max_parallel honored (probe); one session per worker (assert no cross-thread session reuse); recompute after workers → counts from rows; `process_worker` fake invoked per launched worker.
- [ ] Step 2–4: implement mirroring `automation/coordinator.py` (futures set, `_recompute` under lock, shutdown awaits futures). Step 5: commit.

### Task 6: Cancellation at every phase
- [ ] Step 1: failing tests — cancel before provisioning; during proxy test; during launch; between emails → correct email terminal states + preserved owned profiles + no orphan work.
- [ ] Step 2–4: cancel token (`threading.Event` per run) checked at each boundary; persisted `run.status='cancelled'` is source of truth. Step 5: commit.

### Task 7: Startup recovery + race guard
- **Files:** `coordinator.py` (`recover_interrupted_runs`); `main.py` lifespan wiring.
- [ ] Step 1: failing tests — restart after each boundary resumes without duplicate profile/proxy; recovery-while-running no-ops (atomic claim); interrupted runs reconciled.
- [ ] Step 2–4: implement resume-safe recovery + wire into lifespan next to `reconcile_orphan_credentials`; coordinator `shutdown()` in lifespan finally. Step 5: commit.

### Task 8: Route wiring + end-to-end sentinel + performance guards
- **Files:** `routes.py` (POST /runs kicks coordinator), `main.py` (build coordinator).
- [x] Step 1: failing tests — create → coordinator provisions (fakes) → workers reach `launching`/`processing`; run detail shows workers; **sentinel leak** end-to-end (email + proxy secret absent from all JSON, `worker.error`, logs); serialization has no N+1 (single query for workers/counts); SQLite lock contention (N concurrent worker commits, no `database is locked`).
- [x] Step 2–4: wire; ensure `run_detail`/`list_emails` use set-based queries (no per-row credential fetch). Step 5: commit.

Landed as: `tests/manager/test_shop_check_e2e.py` (HTTP → real coordinator on fakes; sentinel absence; hand-off failure never 500s), `test_shop_check_api.py::test_create_hands_the_run_to_the_coordinator`, `test_backend_query_performance.py::test_shop_check_reads_use_constant_statement_count` (already constant — no production change needed). SQLite contention was already covered by `test_shop_check_coordinator.py::test_many_workers_commit_without_sqlite_lock_errors`. The `client` fixture installs an inert coordinator so ordinary API tests never provision/launch.

### Task 9: Gates
- [x] `python -m manager_backend.export_openapi` (only if contract changed) + `pytest tests/manager -m "not slow" -q`; focused shop-check suites; `git diff --check`. Re-run any timing-flaky test once and report both results.

Gate results: response models unchanged → no re-export (`test_openapi_static.py` green). `pytest tests/manager -m "not slow" -q` → **956 passed, 4 skipped**. `git diff --check` clean. No flaky reruns needed.

---

## Risks & unresolved decisions

1. **Sticky vs rotating proxy (design conflict).** Design §3/§13 mandate a **sticky per-profile route** (stable exit for the 5 emails; no per-request rotation). This task's wording says "rotating." **Plan uses sticky-per-profile** (one 711 session directive per worker). **Needs confirmation.**
2. **Caller-supplied profile id.** Durable-ownership-before-creation (compensation matrix option A) needs `create_profile` to accept a supplied `id`, or a thin `create_owned_profile`. If neither is acceptable, fall back to a `0020` `pending_profile` marker + recovery sweep. **Needs confirmation of the profiles-service change.**
3. **Recovery policy: resume vs fail.** Plan chooses **resume-safe** (re-enqueue non-terminal workers) over automation's mark-failed, because Shop-check profiles are expensive to recreate. Diverges from `automation.recover_interrupted_runs`. **Needs confirmation.**
4. **`generate_and_store` writes to the shared proxy pool** (visible on the Proxies screen) and clamps/labels globally. Confirm Shop-check proxies appearing in the pool is acceptable (design §13 says preserve them on cleanup, implying pool membership is fine).
5. **Whether `0020` is needed.** Plan assumes **no** (ownership = worker row). If observability timestamps (`prepared_at`, `launched_at`) or the `pending_profile` marker are wanted, an additive `0020` is required.
6. **Region=None → provider random.** `generate_and_store(country='')` omits the region directive (provider default). Confirm 711's empty-country behavior is "random supported region," not an error.
7. **Launch in unit tests.** All launch goes through `FakeLauncher`; the real `RuntimeManagerLauncher` is covered only by the later authenticated Windows smoke test, not unit tests.

---

## Coverage self-check (against the 8 required areas)
1. Worker allocation → Task 1 (+ idempotency). 2. Ownership → Task 3 + compensation matrix. 3. Proxy provisioning → Task 2 (reuses provider infra, taxonomy). 4. Coordinator → Tasks 5–7 (bounded, per-worker sessions, transitions, atomic claims, cancel, recovery, recompute). 5. Compensation → matrix + Tasks 2/3/6/7. 6. Security → Global Constraints + Task 2/3/8 sentinel tests. 7. Performance → transaction-boundary rules + Task 8 (no N+1, no write-txn across network, SQLite contention). 8. Test plan → test matrix + per-task steps.
