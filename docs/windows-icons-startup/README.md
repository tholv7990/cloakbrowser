# Windows icons & profile-startup — investigation

**Branch:** `fix/windows-icons-profile-startup` · **Status:** research + instrumentation done;
fixes not yet applied (tests/benchmark-first). Nothing committed.

Reference clones (read-only, external, **not** in this repo):
`…/scratchpad/official-ref/CloakBrowser-Manager` and `…/official-ref/CloakBrowser`.
Full cited audits: [official-manager-launch-runtime.md](official-manager-launch-runtime.md),
[official-manager-profile-datamodel.md](official-manager-profile-datamodel.md).

---

## TL;DR

- **The official Manager is Docker + Linux + KasmVNC** (`vnc_manager.py`, `entrypoint.sh`,
  `Dockerfile`). Browsers run headless on virtual X displays viewed over VNC. It has **zero
  Windows-taskbar surface** — repo-wide greps for `AppUserModelID`, `--class`, `WM_CLASS`,
  `taskbar` returned nothing. So it is **not a reference for the icon issue**, but it is a good
  reference for launch/runtime/port/lifecycle behavior.
- **Icons:** our runtime approach (per-window `WM_SETICON` + per-profile `AppUserModelID` in
  `manager_backend/features/runtime/window_icon.py`) is already the *correct* Windows mechanism.
  The residual "switching" is the unavoidable **born-frame** — the window is created carrying the
  CloakBrowser binary's own icon, and we can only override *after* it exists. It cannot be driven
  to exactly zero without editing the verified binary, which is **forbidden** (breaks Ed25519→SHA256
  verification and violates `BINARY-LICENSE.md`).
- **Startup:** added **safe structured timing** (`runtime.start_timing` + `runtime.launch_breakdown`,
  non-secret) so we can see where the wall-clock goes before optimizing. Prime suspects, from the
  reference audit: cold-cache **proxy preflight** (≤5 s), the one-time **google-seed subprocess**
  (≤45 s, gated/idempotent), **tab restore** (≤30 s budget), and per-launch **Playwright driver
  spawn** (unavoidable; both managers pay it).

---

## PART 1 — official Manager, condensed (all citations in the two reference docs)

Path shorthands: `official:` = the cloned reference, `ours:` = `manager_backend/`.

| Topic | Official | Ours | Note |
|---|---|---|---|
| Launch API | `launch_persistent_context_async`, awaited on the request (`official: browser_manager.py:217-234`, `main.py:534`) | sync `launch_persistent_context` in a **worker thread** (`ours: launcher.py:534`, `worker.py`) | ours returns instantly, streams state |
| Playwright | fresh driver **per launch** | fresh driver **per launch** | neither pools — shared cost |
| CDP port | rotating `5100–5199` with `socket.bind` probe (`official: browser_manager.py:364-377`) | **none** for interactive launches; `--remote-debugging-port` is blocklisted (`ours: profiles/schemas.py:26-27`) | ours removes a local attack surface |
| Process tracking | Playwright `context` only, no pid | pid + create_time + owned udd (`ours: launcher.py:389-410`) | ours needs it (no container, restart reconcile) |
| Close detection | Playwright `close` event (`official: browser_manager.py:268-270`) | OS-pid poll (sync loop not pumped) (`ours: launcher.py:490-520`) | ours can't use the event |
| Duplicate guard | in-memory set only | 3 layers: registry + `O_EXCL` file lock + DB (`ours: manager.py`, `locks.py`) | ours safe cross-process |
| Concurrency | uncapped (bounded by display/port ranges) | `BoundedSemaphore(max_concurrent_launches=2)` (`ours: manager.py:50`) | ours protects the desktop |
| Proxy | free-form string, **no preflight** (`official: browser_manager.py:22-38,210`) | keyring creds + connectivity gate + exit-IP geo/WebRTC (`ours: proxies/service.py`) | ours far safer |
| Default search | plain `Preferences` write (`official: browser_manager.py:126-142`) | `initial_preferences` + Secure-Prefs MAC restamp (`ours: google_seed.py`) | official's likely **ineffective** on the stealth binary |

**Safe to adopt** (small, no security impact): pre-launch **stale-Singleton cleanup** (unlink
`SingletonLock/Cookie/Socket`, `official: browser_manager.py:186-190`) to avoid "profile in use"
after a hard kill; the **rotating-port + `socket.bind` probe** for our google-seed `_free_port`;
`--use-angle=swiftshader`/`--test-type` for GPU-less diagnostic launches.

**Data-model gaps worth adopting** (from the data-model audit): per-profile **OS/platform spoof**
(`--fingerprint-platform` is reserved at `ours: profiles/schemas.py:17` but never emitted),
per-profile **screen resolution**, and **GPU renderer** — these are genuine anti-detect gaps
(today every profile reports 1920×1080 and no OS spoof). Fold any of them into
`fingerprint_config_hash` so they stay tamper-evident.

**Explicitly reject** (incompatible with our model): no-preflight launches; plaintext proxy
strings; in-memory-only runtime state; blocking the request until running; the `close`-event
detection; an exposed per-profile CDP port; and the plain-`Preferences` DSE write. Our seed
handling (unique 64-bit + DB constraint) is strictly better than theirs (`randint(10000,99999)`,
no constraint → collisions by ~350 profiles).

---

## PART 2 — Windows taskbar icon audit

### The ten questions, answered from source

1. **Which process owns the visible browser window?** The **CloakBrowser Chromium browser
   (main) process** — a grandchild of our backend spawned via Playwright's Node driver, located by
   `--user-data-dir` (`ours: launcher.py:389-410`; the main process has no `--type=`). **Not**
   Plasma, and not the Python backend.
2. **Which executable supplies the taskbar icon?** The **downloaded CloakBrowser Chromium
   binary's** embedded PE icon (what Chrome sets via its own `WM_SETICON` at window creation). The
   Plasma *app* window's icon is a separate concern owned by the Plasma shell/installer.
3. **Can Plasma change the CloakBrowser executable icon legally and safely?** **No.** It would break
   the download-time Ed25519→SHA256 verification (`cloakbrowser/download.py`) and violate
   `BINARY-LICENSE.md` (no modification/repackaging). Hard constraint.
4. **Plasma icon, CloakBrowser icon, or profile-specific?** Policy: **one approved Plasma-brand
   icon on all profile windows** (the plasma-dart), applied at runtime. Per-profile *images* are
   possible but low-value; per-profile *identity* (grouping) is handled by AUMID (below). Current
   code already applies the Plasma dart.
5. **Group all profiles under Plasma, or separately by profile?** Current + recommended: **separately
   by profile** — each window gets a distinct `AppUserModelID` (`CloakBrowser.Profile.{seed}`,
   `ours: window_icon.py:216`) so profiles are individually identifiable taskbar buttons rather than
   one merged Chrome group. (Documented policy; switch to a single Plasma group by using one AUMID
   if preferred.)
6. **Can an explicit AppUserModelID solve grouping?** **Yes** — set per window via the window
   `IPropertyStore` `System.AppUserModel.ID` + relaunch icon (`ours: window_icon.py:66-96`). This is
   the correct Windows grouping mechanism and is already implemented.
7. **Does Chromium need `--class`, `--app`, shortcut metadata, or another mechanism?** No. `--class`
   is **Linux/X11** (`WM_CLASS`) — irrelevant on Windows. `--app` makes a chrome-less app window (not
   desired). On Windows the correct levers are **`WM_SETICON`** (window/title-bar icon) + **AUMID**
   (taskbar identity/grouping/relaunch icon) — both applied at runtime, no binary change.
8. **Does Windows ignore icon changes because of the icon cache?** The Explorer icon cache affects
   **file/shortcut** icons, not live `WM_SETICON` window icons — our runtime override applies
   immediately and is not cached. The cache is only relevant to the **installed Plasma shortcut**
   icon (set a stable AUMID + icon there).
9. **Will modifying the verified browser binary break integrity verification?** **Yes** (and it is
   prohibited) — see Q3.
10. **Can the desired behavior be implemented without modifying the binary?** **Yes — entirely.**
    Runtime `WM_SETICON` + per-window AUMID (`window_icon.py`) + correct Plasma shell/installer icon.
    The single irreducible limitation is the ~1-frame **born-frame** at window creation.

### What the current code already does (this session's work, on `main`)

`window_icon.py` draws a cached plasma-dart `.ico`, applies it via `WM_SETICON` (small+big) to each
profile window, and sets a per-profile AUMID + relaunch icon. `launcher.py` front-loads an
**icon burst** (started before the blocking process scan; ~15 ms cadence for 5 s using one cheap
pid scan) so the Plasma icon lands within a frame or two and keeps winning while Chrome re-sets its
own icon during startup. This already fixed the *repeated* flicker (commits `e66fa6c`, `d61db9f`);
the residual is the single born-frame.

### Acceptance criteria (intended behavior)

- Plasma desktop window shows the Plasma icon (owned by the shell/installer — see
  `docs/architecture/plasma-desktop-cloud/desktop-packaging.md`; when packaged with Tauri the
  FastAPI sidecar runs windowless, so **no Python console taskbar entry**).
- Installed Start-menu/desktop shortcut shows the Plasma icon (stable shortcut AUMID + icon).
- Each profile window shows the approved Plasma icon within ~1 frame and stays on it.
- Profiles are **separate** taskbar buttons per the documented AUMID policy (Q5).
- Behavior survives app restart and Windows icon caching; **no** CloakBrowser verification weakened;
  **no** browser binary modified.

### Tests

- **Automated (exists / extend):** `tests/manager/test_window_icon.py` +
  `tests/manager/test_launcher.py::test_icon_burst_*` cover `.ico` generation and that the burst
  stamps without a probe. These can assert *mechanics* (icon built, burst fires, AUMID call made)
  but **not** the visual taskbar result — Windows compositor state isn't observable in CI.
- **Manual (deterministic checklist):** see [manual-icon-verification.md](manual-icon-verification.md).

---

## PART 3 — profile-startup instrumentation

### What was added (this branch, uncommitted)

`manager_backend/features/runtime/timing.py` — a `StartTimer` that records named stage durations and
emits **one non-secret JSON line** (canonical profile UUID + stage names + integer ms only) on the
`manager.runtime.timing` logger. Deliberately **not** routed through the profile-log channel
(`logs.py`), which is an allow-listed safe-message surface.

Wired through the real start path:

- `manager.py` (`RuntimeManager.start`): `lock_acquire`, `profile_load` (incl. extension
  validation via `_snapshot`), `session_create`.
- `worker.py` (`ProfileWorker.run`): `proxy_preflight`, `launch_gate_wait` (time parked on the
  launch semaphore), `browser_launch`; emits `runtime.start_timing` right after the `running`
  transition. The semaphore was switched to explicit acquire/release **preserving** the "wraps only
  the launch phase" behavior (verified by the existing concurrency test).
- `launcher.py` (`CloakPersistentLauncher.launch`): an internal breakdown timer logs
  `runtime.launch_breakdown` → `google_seed`, `context_creation` (the Playwright/browser black box),
  `handle_locate`, `tab_restore`. `launch()`'s signature is unchanged so injectable test fakes stay
  intact.

Example lines (illustrative shape, not real numbers):

```json
{"event":"runtime.start_timing","profile_id":"<uuid>","stages_ms":{"lock_acquire":0,"profile_load":5,"session_create":7,"proxy_preflight":312,"launch_gate_wait":0,"browser_launch":840},"total_ms":1170}
{"event":"runtime.launch_breakdown","profile_id":"<uuid>","stages_ms":{"google_seed":2,"context_creation":690,"handle_locate":40,"tab_restore":110},"total_ms":845}
```

Regression test: `tests/manager/test_runtime_manager.py::test_start_emits_structured_stage_timing`
(drives `start` with a fake launcher, asserts the structured line + expected stage keys + that the
payload contains nothing beyond `event/profile_id/stages_ms/total_ms`). **89 runtime tests pass.**

### How to benchmark (needs a live Windows launch — the binary + a desktop)

1. Run the backend so the timing logger is visible (it logs at INFO on `manager.runtime.timing`;
   ensure app logging shows INFO, or add a handler for that logger).
2. Launch a profile **without** a proxy → capture `runtime.start_timing` / `runtime.launch_breakdown`.
3. Launch a profile **with** a proxy + "test before launch" ON, cold cache → capture again.
4. Repeat within 60 s (warm proxy cache) → capture again.
5. Compare `proxy_preflight` and `context_creation`/`tab_restore` across the three.

This is the "before" measurement. Only after we see real numbers do we choose optimizations —
candidate levers (from the audit, none applied yet): make preflight fully async/parallel to the
non-proxy launch prep, cache the google-seed result harder, cap/short-circuit tab restore, and
consider a warm Playwright driver. **Do not** remove the existing preflight cache, 5 s gate,
exit-IP WebRTC reuse, snapshot cache, or indexes — those are recent wins to preserve.

---

## What still needs a live Windows run (cannot be done here)

- **Benchmark numbers** (above) — needs the ~200 MB binary + a real desktop session.
- **Manual icon verification** — the taskbar is a visual/compositor outcome; see the checklist doc.

## Not done yet (by design — tests/benchmark first)

No fixes to the icon or startup paths beyond the instrumentation. Recommended next steps are listed
under PART 3; they wait on real "before" numbers.
