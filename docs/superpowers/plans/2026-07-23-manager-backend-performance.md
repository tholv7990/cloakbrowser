# Manager Backend Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the local manager responsive at 1,000 profiles and 100,000 historical runtime sessions by eliminating unbounded ORM loading, N+1 queries, and full-history WebSocket polling.

**Architecture:** Preserve the FastAPI and SQLite interfaces while reshaping reads into set-based SQL. Add only query-plan-backed indexes through Alembic and use a small per-WebSocket change marker instead of a general response cache.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, SQLite WAL, pytest.

## Global Constraints

- Preserve all public API response schemas and authentication behavior.
- Never cache, persist, log, or return proxy or website credentials.
- Keep WAL, foreign keys, busy timeout, and current SQLite durability settings.
- Do not use timing thresholds in the normal test suite.
- Do not touch `manager/frontend`, browser-engine code, or any `.rar` file.
- Test at a target scale of 1,000 profiles, 100 runtime sessions per profile, 1,000 proxies, and 100 media assets.

---

### Task 1: Query-count instrumentation and set-based proxy/media counts

**Files:**
- Create: `tests/manager/test_backend_query_performance.py`
- Modify: `manager_backend/features/proxies/service.py`
- Modify: `manager_backend/features/media/service.py`

**Interfaces:**
- Consumes: SQLAlchemy `Engine` events and existing `list_proxies()` / `list_assets()` APIs.
- Produces: `_proxy_assignment_counts(session, proxy_ids) -> dict[str, int]` and `_media_assignment_counts(session, asset_ids) -> dict[str, int]`.

- [ ] **Step 1: Write failing constant-query tests**

Add a typed context manager that counts `before_cursor_execute` events, seed 2 and 100 objects, and assert each list function uses the same statement count at both sizes. Assert returned assignment counts remain correct.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest tests/manager/test_backend_query_performance.py -k "proxy or media" -q
```

Expected: the large collections execute roughly one additional statement per returned row.

- [ ] **Step 3: Implement grouped aggregate queries**

For proxies, select `Profile.proxy_id, count(Profile.id)` filtered to requested IDs and group by `Profile.proxy_id`. For media, select `profile_media_assets.c.media_asset_id, count()` joined to non-deleted profiles and grouped by media ID. Pass the resulting count mapping into serialization rather than querying inside each serializer call.

- [ ] **Step 4: Verify focused and API tests**

```powershell
python -m pytest tests/manager/test_backend_query_performance.py tests/manager/test_proxy_api.py tests/manager/test_media_api.py -q
```

Expected: all pass and list query counts remain constant.

- [ ] **Step 5: Commit**

```powershell
git add manager_backend/features/proxies/service.py manager_backend/features/media/service.py tests/manager/test_backend_query_performance.py
git commit -m "perf(manager): batch proxy and media assignment counts"
```

### Task 2: Bound profile runtime loading

**Files:**
- Modify: `manager_backend/models.py`
- Modify: `manager_backend/features/profiles/service.py`
- Modify: `tests/manager/test_backend_query_performance.py`
- Modify: `tests/manager/test_profiles_api.py`

**Interfaces:**
- Consumes: the database invariant allowing at most one active runtime per profile.
- Produces: profile serialization with the same `runtime_state` field without loading terminal history.

- [ ] **Step 1: Write failing history-materialization tests**

Seed 100 terminal runtime rows plus one active row for a profile, call list and detail, and inspect the SQLAlchemy identity map/query results. Assert terminal `RuntimeSession` objects are not materialized and `runtime_state` remains `running`. Add a stopped-only case that returns `stopped`.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/manager/test_backend_query_performance.py -k profile_runtime -q
```

Expected: the current `selectinload(Profile.runtime_sessions)` materializes all seeded history.

- [ ] **Step 3: Replace history eager loading**

Remove `selectinload(Profile.runtime_sessions)` from profile list/detail queries. Load active runtime state for the returned profile IDs with one filtered query and pass a `dict[profile_id, state]` into `profile_to_dict`. Preserve the model property for non-list callers, but ensure API serialization never triggers lazy loading.

- [ ] **Step 4: Verify profile behavior**

```powershell
python -m pytest tests/manager/test_backend_query_performance.py tests/manager/test_profiles_api.py tests/manager/test_runtime_state.py -q
```

Expected: bounded loading and unchanged runtime-state responses.

- [ ] **Step 5: Commit**

```powershell
git add manager_backend/models.py manager_backend/features/profiles/service.py tests/manager/test_backend_query_performance.py tests/manager/test_profiles_api.py
git commit -m "perf(manager): bound profile runtime-state loading"
```

### Task 3: Set-based resource and session history reads

**Files:**
- Modify: `manager_backend/features/resources/service.py`
- Modify: `tests/manager/test_backend_query_performance.py`
- Modify: `tests/manager/test_resources_api.py`

**Interfaces:**
- Consumes: existing resource/session response dictionaries.
- Produces: joined `(RuntimeSession, profile_name)` rows with unchanged response values.

- [ ] **Step 1: Write failing query-bound tests**

Seed active runtimes and recent sessions for distinct profiles. Assert `build_snapshot()` and `list_sessions()` query counts do not increase between 2 and 100 profiles. Reset the module snapshot/process caches between cases.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/manager/test_backend_query_performance.py -k "resource or session" -q
```

Expected: per-runtime `Session.get(Profile, ...)` calls increase query count.

- [ ] **Step 3: Join profile names**

Select `RuntimeSession` with `Profile.name` using an inner join for rows protected by the foreign key. Build response dictionaries from the joined name and remove per-row `session.get()` calls.

- [ ] **Step 4: Verify focused tests**

```powershell
python -m pytest tests/manager/test_backend_query_performance.py tests/manager/test_resources_api.py -q
```

Expected: constant statement counts and unchanged API output.

- [ ] **Step 5: Commit**

```powershell
git add manager_backend/features/resources/service.py tests/manager/test_backend_query_performance.py tests/manager/test_resources_api.py
git commit -m "perf(manager): join profile names in runtime reads"
```

### Task 4: Bound and cache live WebSocket snapshots

**Files:**
- Create: `manager_backend/features/runtime/snapshots.py`
- Modify: `manager_backend/main.py`
- Modify: `tests/manager/test_runtime_api.py`
- Modify: `tests/manager/test_backend_query_performance.py`

**Interfaces:**
- Produces: `runtime_snapshot_marker(session) -> tuple[object, ...]` and `load_runtime_snapshot(session) -> tuple[list[dict], int]`.
- Consumes: the frontend contract requiring an initial `runtime.snapshot`, active state changes, messages, and running count changes.

- [ ] **Step 1: Write failing idle-poll and contract tests**

Extract the snapshot loop behind functions that can be counted. Assert repeated unchanged marker checks do not call the full payload loader. Assert the initial snapshot and a runtime transition still deliver the existing JSON shape. Assert historical stopped rows are not included in the live payload.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/manager/test_runtime_api.py tests/manager/test_backend_query_performance.py -k websocket -q
```

Expected: current code reloads all historical rows on every approximately 50 ms loop.

- [ ] **Step 3: Implement selective snapshot caching**

Move runtime snapshot SQL into `snapshots.py`. Query only active runtimes for the live payload. Use a lightweight aggregate marker covering active row count/latest update and the active count excluding deleted profiles. Cache the last marker/payload per WebSocket connection. Check at 250 ms intervals while continuing to await diagnostic events with the same maximum interval.

- [ ] **Step 4: Verify runtime and realtime contracts**

```powershell
python -m pytest tests/manager/test_runtime_api.py tests/manager/test_contract.py tests/manager/test_backend_query_performance.py -q
```

Expected: initial and changed snapshots pass; idle full-load count remains one.

- [ ] **Step 5: Commit**

```powershell
git add manager_backend/features/runtime/snapshots.py manager_backend/main.py tests/manager/test_runtime_api.py tests/manager/test_backend_query_performance.py
git commit -m "perf(manager): cache bounded live runtime snapshots"
```

### Task 5: Query-plan-backed indexes and target-scale benchmark

**Files:**
- Create: `manager_backend/migrations/versions/0015_performance_indexes.py`
- Modify: `manager_backend/models.py`
- Create: `tests/manager/test_performance_index_migration.py`
- Create: `benchmarks/manager_backend_scale.py`
- Modify: `docs/superpowers/specs/2026-07-23-manager-backend-performance-design.md`

**Interfaces:**
- Produces indexes `ix_profiles_proxy_id`, `ix_runtime_sessions_profile_created_at`, `ix_runtime_sessions_created_at_id`, and `ix_profile_media_assets_media_profile`.
- Produces a standalone benchmark that prints query counts and elapsed time.

- [ ] **Step 1: Write failing migration and query-plan tests**

Upgrade a temporary database to head, inspect `PRAGMA index_list`, and assert all four indexes exist. Use `EXPLAIN QUERY PLAN` for proxy assignment, media reverse lookup, per-profile runtime history, and recent-session ordering; assert the intended index names appear. Downgrade to `0014_shopify` and assert the indexes are absent.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest tests/manager/test_performance_index_migration.py -q
```

Expected: revision/indexes do not exist.

- [ ] **Step 3: Add migration and matching metadata**

Create all four non-unique indexes in `upgrade()` and drop them in reverse order in `downgrade()`. Add matching `Index` declarations to `Profile`, `RuntimeSession`, and `profile_media_assets` metadata.

- [ ] **Step 4: Add and run the scale benchmark**

Seed 1,000 profiles, 100 sessions per profile, 1,000 proxies, and 100 media assets in a temporary on-disk SQLite database. Print elapsed milliseconds and SQL statement counts for profile page 100, proxy list, media list, recent sessions, and live snapshot. Keep assertions to response size and constant-query bounds.

```powershell
python benchmarks/manager_backend_scale.py
```

- [ ] **Step 5: Run full verification**

```powershell
python -m pytest tests/manager -m "not slow" -q
python -m pytest tests/manager/test_openapi_static.py tests/manager/test_contract.py -q
git diff --check
```

Expected: all manager tests pass. If the known diagnostics worker-start test flakes, rerun it alone and report both results rather than weakening it.

- [ ] **Step 6: Commit**

```powershell
git add manager_backend/models.py manager_backend/migrations/versions/0015_performance_indexes.py tests/manager/test_performance_index_migration.py benchmarks/manager_backend_scale.py docs/superpowers/specs/2026-07-23-manager-backend-performance-design.md
git commit -m "perf(manager): add measured SQLite indexes and scale benchmark"
```
