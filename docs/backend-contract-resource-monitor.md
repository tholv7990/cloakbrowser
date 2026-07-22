# Backend contract — Resource monitor (`GET /resources`)

**Status:** frontend built (mock + real adapter, panel on the Diagnostics screen). Needs the real endpoint in `manager_backend`.

**Owner:** backend (Codex). Frontend is done and polls this endpoint every 2s while the panel is visible.

## Why

Per-profile CPU/RAM **visibility** while profiles are running — the one thing the competitor (Quantum) has here that we lacked. This is **observability only**: read-only sampling. Do **not** cap, prioritize, set affinity, or use Job Objects — Quantum doesn't either, and hard allocation is out of scope. The user watches this and decides to stop a heavy profile manually.

## Endpoint

```
GET /api/v1/resources        -> 200 ResourceSnapshot
```

- Auth: same session-cookie + origin check as the rest of the API.
- Consider gating behind the **`browser_runtime`** capability (it only makes sense when runtime is enabled). If the capability is off, the frontend won't request it, but returning 200 with empty `profiles` is also fine.
- Must be **cheap and non-blocking** — it is polled every 2s. Cache the snapshot ~0.8s (see below). **Do not** fold per-profile resource data into `GET /profiles` or the runtime list — keep it on this dedicated endpoint so the profile table stays fast.

## Response shape

Mirrors the TS types in `manager/frontend/src/types/api.ts` (`ResourceSnapshot`). All CPU percentages are **0–100, already divided by logical core count** (so they match Task Manager), rounded to 1 decimal. Memory is **bytes** (RSS).

```jsonc
{
  "generated_at": "2026-07-22T07:00:00Z",   // ISO-8601 UTC
  "system": {
    "cpu_percent": 23.4,                     // whole-system CPU 0-100
    "memory_percent": 61.2,                  // whole-system RAM 0-100
    "memory_used_bytes": 10500000000,
    "memory_total_bytes": 17000000000,
    "logical_cpus": 12
  },
  "backend": {                               // the manager_backend process itself
    "cpu_percent": 1.1,
    "memory_bytes": 138000000,
    "process_count": 1
  },
  "browsers": {                              // aggregate across ALL running profile browsers
    "cpu_percent": 44.0,
    "memory_bytes": 3200000000,
    "process_count": 37,
    "profiles_running": 5
  },
  "profiles": [                              // ONE row per RUNNING profile, sorted heaviest-first
    {
      "profile_id": "prof_abc",
      "profile_name": "marketplace-us-01",
      "runtime_state": "running",            // same enum as RuntimeSession.state
      "cpu_percent": 18.2,
      "memory_bytes": 820000000,
      "process_count": 9
    }
  ]
}
```

Notes:
- `profiles` contains only profiles in a live state (`starting` / `running` / `stopping`). Stopped profiles are omitted.
- Sort `profiles` **descending by `cpu_percent`, then `memory_bytes`** (frontend renders in the order received).
- There is **no `desktop` field** (Quantum has one for its Tauri shell; we're a web app — omit it).

## Implementation notes (psutil)

- We already track `RuntimeSession.browser_pid` per running profile. Prefer resolving each profile's process tree from that PID: `psutil.Process(browser_pid).children(recursive=True)` + the root — more reliable than command-line substring matching. (Quantum matches `user_data_dir` in the cmdline because it doesn't persist the PID; we do, so use it.)
- Do **one** pass. If you must scan (`psutil.process_iter(["pid","name","cmdline"])`), do it once and bucket by profile, not once per profile.
- CPU: `proc.cpu_percent(interval=None)` returns cumulative-since-last-call per process; **divide the summed value by `psutil.cpu_count(logical=True)`** so a busy multi-thread browser reads 0–100, not 0–N×100. Guard `psutil.NoSuchProcess/AccessDenied/ZombieProcess`.
- Memory: sum `proc.memory_info().rss` across the tree.
- **Cache the whole snapshot ~0.8s** behind a module-level `(timestamp, snapshot)` so 2s polling (and any concurrent viewers) never triggers back-to-back scans. Reference: Quantum's `backend/services/resource_service.py` (`_CACHE_SECONDS = 0.8`).
- Keep it read-only. No priority/affinity/limits.

## Reference implementation

`Quantum-Source-Clean/backend/services/resource_service.py` — `resource_snapshot()` is a clean ~150-line template (drop its `desktop` block; swap its cmdline matching for our `browser_pid` tree).

## Frontend already in place

- Types: `ResourceSnapshot` et al. in `src/types/api.ts`.
- Adapter: `getResources()` in `api/adapter.ts` / `api/real.ts` (`GET /resources`) / `mocks/mockApi.ts` (synthesizes from running mock profiles).
- Hook: `useResources()` in `features/diagnostics/api.ts` — `refetchInterval: 2000`, `refetchIntervalInBackground: false` (pauses when the tab is hidden).
- UI: `features/diagnostics/ResourceMonitor.tsx`, mounted on the Diagnostics screen. Fully EN/VI localized (`res.*`).
