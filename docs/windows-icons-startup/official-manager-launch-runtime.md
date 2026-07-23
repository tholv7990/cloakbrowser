# Official CloakBrowser-Manager — launch/runtime reference audit

READ-ONLY comparison of the official `CloakBrowser-Manager` (cloned reference) against our Plasma
`manager_backend`. Nothing modified in either tree. `official:` = the cloned reference,
`ours:` = `manager_backend/`, `wrapper:` = `cloakbrowser/` (the shared client both call).
CONFIRMED = read in source; INFERRED = reasoned, labeled.

**Orientation.** The official manager is a **single-process, Linux/Docker/KasmVNC** app: one
async FastAPI loop launches browsers on remote virtual X displays, proxies VNC (RFB) and CDP over
WebSocket to a React SPA, keeps runtime state **in memory**. Ours is **Windows-native, headed,
local**: browsers launch on the real desktop with per-profile taskbar identity, runtime state is
**persisted in SQLite and reconciled on restart**, launches run in **background worker threads**
behind a concurrency semaphore, and proxies are **network-preflighted**. Shared: both call the
wrapper's `launch_persistent_context*`.

## 1. Starting a browser
- **Official — async.** `official: browser_manager.py:15` imports `launch_persistent_context_async`;
  sole call site `browser_manager.py:217-234` inside `BrowserManager.launch()` (`:167`), passing
  `user_data_dir, headless, proxy, args, timezone, locale, humanize, human_preset, geoip,
  color_scheme, user_agent, viewport` and `env={**os.environ, "DISPLAY": f":{display}"}`. Awaited in
  the HTTP handler `official: main.py:534`.
- **Ours — sync.** `ours: launcher.py:534` (`CloakPersistentLauncher.launch`, `:523`) calls
  `cloakbrowser.launch_persistent_context(...)`, always headed (`headless=False`, `:536`), never on
  the request path — runs in a worker thread (§13).

## 2. Playwright init — per launch in BOTH
- Sync: `wrapper: browser.py:573` `sync_playwright().start()`, `pw.stop()` monkey-patched onto
  `context.close` (`wrapper: browser.py:597-603`).
- Async: `wrapper: browser.py:722` `await async_playwright().start()`.
- Official keeps only the `context` per profile (`official: browser_manager.py:150-156`, `:217`);
  ours wraps it in `_PersistentContextHandle` (`ours: launcher.py:332`, `:541`).
- **Consequence:** every launch spawns a Node driver subprocess in both — no warm/pooled driver.

## 3. CDP port
- **Official allocates a real TCP CDP port per launch.** `BASE_CDP_PORT=5100`, range 100
  (`official: browser_manager.py:145-146`); `_allocate_cdp_port()` walks a rotating counter with a
  `socket.bind` probe (`:364-377`); injected as `--remote-debugging-port` (`:207`), stored on
  `RunningProfile.cdp_port` (`:264`), proxied via httpx + WS passthrough (`main.py:858-1016`).
- **Ours allocates none for interactive launches.** `persistent_context_kwargs` (`ours: launcher.py:278-310`)
  emits no debug port; `--remote-debugging-port`/`--remote-debugging-pipe` are blocklisted
  (`ours: profiles/schemas.py:26-27`). Only in-process CDP via `context.new_cdp_session` for tab
  snapshots (`ours: launcher.py:436`). A `cdp_endpoint` column exists (`ours: models.py:388`) but is
  never populated at launch; reconcile treats empty as non-reconnectable (`ours: reconcile.py:82-84`).
  The only debug port we open is the isolated google-seed subprocess on an ephemeral `_free_port()`
  (`ours: google_seed.py:58-63,129-132`), closed gracefully.

## 4. Tracking browser processes
- **Official tracks the Playwright object, not the OS process** — `RunningProfile` holds
  `context, display, ws_port, cdp_port`, no pid/create_time (`official: browser_manager.py:149-156`).
  The container is the isolation boundary.
- **Ours tracks pid + create_time + owned udd.** `_locate_browser()` scans all processes for a
  `chrome` whose `--user-data-dir` matches (`ours: launcher.py:389-410`, parse `:322-329`, normalize
  `:313-319`), records `browser_pid`/`browser_created_at` (`:403-406`); persisted by the worker
  (`ours: worker.py:50-60`, called `:86`). Full scan needed because Playwright hides Chrome behind a
  Node driver (`ours: launcher.py:391-395`).

## 5. Detecting a closed browser
- **Official — Playwright `close` event** (`official: browser_manager.py:268-270` → `_on_browser_closed`,
  `:289-296`).
- **Ours — OS poll** because the sync loop isn't pumped in the worker thread: `is_closed()`
  (`ours: launcher.py:490-520`) does a cheap pid liveness every call (~0.1 s), throttling the full
  scan/snapshot/icon to `_PROBE_INTERVAL=2.0s`; `_process_alive()` verifies pid+create_time
  (`:412-423`). Rationale cited at `ours: launcher.py:493-498`. Cross-restart: `reconcile_runtimes`
  (`ours: reconcile.py:88-151`) marks each active runtime crashed/detached/reconnected; the official
  has no equivalent (in-memory, reset each container start).

## 6. Profile directories
- **Official:** `DATA_DIR=/data` (`official: database.py:14`), `user_data_dir=/data/profiles/<uuid>`
  (`:94`); Docker volume (`docker-compose.yml:6-7`, `Dockerfile:62`). Stale Singleton files unlinked
  before launch (`official: browser_manager.py:187-190`) and by entrypoint (`entrypoint.sh:14-16`).
- **Ours:** `data_root=%LOCALAPPDATA%\CloakBrowser\Manager` (`ours: config.py:10-14`),
  `profile_root=data_root/profiles` (`:40-42`), `profile_dir=profile_root/<id>` (`ours: launcher.py:72`),
  Chrome `--user-data-dir` = `profile_dir/user-data` (`:529,533`). The extra nesting co-locates
  `last-session.json` (`:106,464`) and `.runtime.lock` (`ours: manager.py:47`).

## 7. Preventing duplicate launches
- **Official:** in-memory `self.running` + `self._launching` under an `asyncio.Lock`
  (`official: browser_manager.py:160-163`, reject `:171-174`); route double-check `main.py:530-531`.
  No cross-process lock.
- **Ours — three layers:** in-memory registry under `threading.Lock` (`ours: manager.py:63-68`);
  cross-process `O_CREAT|O_EXCL` file lock (`ours: locks.py:18-37`) at `profiles/<id>/.runtime.lock`
  with owner pid+create_time for stale GC (`ours: reconcile.py:35-56`); DB-level guard in
  `create_runtime_session` (`ours: service.py:64-77`).

## 8. Simultaneous launches / concurrency
- **Official — no explicit cap;** `self._lock` held only for brief set mutations
  (`official: browser_manager.py:171-174,272-274`); bounded implicitly by display range
  (`vnc_manager.py:22-37`) and CDP-port range 100. Startup auto-launch is sequential with 60 s per
  profile (`browser_manager.py:342-362`).
- **Ours — `BoundedSemaphore(max_concurrent_launches)`** default 2, range 1–8
  (`ours: manager.py:50`, `config.py:26`), held around the launch+ready phase only (`ours: worker.py:83-92`).

## 9. Fingerprint args
- **Official — granular per-attribute `--fingerprint-*` from DB columns.** `_build_fingerprint_args`
  (`official: browser_manager.py:379-415`): always `--disable-infobars --test-type
  --use-angle=swiftshader`, then conditional `--fingerprint`, `-platform`, `-gpu-vendor`,
  `-gpu-renderer`, `-hardware-concurrency`, `-screen-width/height`.
- **Ours — seed + preset + a few flags.** `persistent_context_kwargs` (`ours: launcher.py:283-306`)
  emits `--fingerprint=<seed>`, a window-size flag, and `--fingerprint-webrtc-ip` only when WebRTC
  routes through the proxy (`:290-296`); passes `fingerprint_preset, browser_version, user_agent,
  proxy, locale, timezone` as kwargs, and the wrapper expands the preset. Carries
  `fingerprint_revision`/`fingerprint_config_hash` for change tracking (`:75-76`).

## 10. Proxy
- **Official** normalizes a free-form string (`official: browser_manager.py:22-38`), validates
  syntax (`:41-53`), passes `proxy=` to Playwright (`:210-234`). **No connectivity test.**
- **Ours** resolves a structured record; `resolve_proxy_url`→`build_proxy_url` URL-encodes creds and
  is never persisted/logged (`ours: proxies/service.py:213-239`); worker preflights
  (`ours: worker.py:82` → `build_proxy_preflight.preflight`, `proxies/service.py:312-353`), derives
  timezone+locale from the measured exit IP for `geo_mode="proxy"` (`:267-279`), spoofs WebRTC IP
  (`ours: launcher.py:290-296`).

## 11. Preferences / bookmarks / default search
- **Official** writes plain `Bookmarks` + `Preferences` on first launch (`official: browser_manager.py:56-142`,
  called `:193`) — a detection-test bookmark tree (`:63-122`) and a **DuckDuckGo** DSE block
  (`:126-142`).
- **Ours** performs `initial_preferences` + Secure-Preferences MAC restamp because the stealth binary
  treats the DSE as a protected pref: `ensure_google_search` (`ours: launcher.py:181-199`, called
  `:532`), `google_seed.seed` writes `initial_preferences`, deletes `Secure Preferences`, launches
  the real binary off-screen to stamp a valid MAC, closes gracefully via CDP, inserts a Google
  `keywords` row (`ours: google_seed.py:111-137`). Also restores the previous tab session
  (`ours: launcher.py:247-261`, capped 25 URLs / 30 s).
- **INFERRED gap:** the official's plain-`Preferences` write only happens when the file is absent and
  is exactly what ours documents as *rejected as tampering* by the stealth binary
  (`ours: launcher.py:110-115`, `google_seed.py:3-22`) — so on the current binary the official's
  DuckDuckGo default likely does not reliably take effect. A citable behavioral gap.

## 12. Network checks before launch
- **Official:** none (URL syntax only, `official: browser_manager.py:41-53`).
- **Ours:** a bounded, cached connectivity gate — `build_proxy_preflight` (`ours: proxies/service.py:312-353`),
  60 s cache (`_PREFLIGHT_CACHE_MAX_AGE`, `:282`; `_cached_quick_test`, `:291-309`),
  `tester.run_fast(timeout_seconds=5)` (`ours: proxies/testing.py:132-167`); failure →
  `proxy_preflight_failed` (409) → `runtime.crashed` (`ours: worker.py:106-122`).

## 13. Blocking on the request thread
- **Official:** the launch endpoint blocks until the browser is up (`official: main.py:525-547`,
  `browser_mgr.launch` awaits VNC start incl. `asyncio.sleep(0.5)` `vnc_manager.py:79`).
- **Ours:** `RuntimeManager.start` returns fast after writing a `queued` row and spawning a
  `ProfileWorker` (`ours: manager.py:62-105`); the thread does preflight→starting→launch→running
  (`ours: worker.py:79-104`), streaming states to the DB.

## 14. Windows icons / AppUserModelID in the official — NONE
- Repo-wide greps for `AppUserModelID`, `--class`, `WM_CLASS`, `window[-_]class`, `taskbar`,
  `set_app_id` = **no matches**. The lone icon-ish token is `official: browser_manager.py:134`
  `"favicon_url": "https://duckduckgo.com/favicon.ico"` (the seeded DSE favicon), not a
  taskbar/window mechanism. Environment: `Dockerfile:10` `python:3.12-slim` + KasmVNC
  (`Dockerfile:35-40`); windows render on Xvnc (`vnc_manager.py`). No Windows shell surface.
- **Ours** has the full Windows taskbar-identity subsystem the official lacks:
  `ours: window_icon.py:66-96,188-236` (`WM_SETICON` + per-profile AUMID via `IPropertyStore`),
  icon burst front-loaded before `_locate_browser` (`ours: launcher.py:353-379`).

## 15. Startup-performance differences
Both spawn a fresh driver per launch (equal cost). **Official faster because:** no proxy preflight
(`official: browser_manager.py:210-213` vs our ≤5 s gate); no google-seed subprocess (ours ≤45 s
once, gated); no pre-launch full process scan / icon burst / tab restore. **Official slower
because:** starts an Xvnc subprocess per launch with a 0.5 s settle (`vnc_manager.py:39-94`);
allocates+binds a TCP CDP port every launch (`browser_manager.py:179-207,364-377`); injects a
clipboard init script (`browser_manager.py:236-257`). **Throughput:** official uncapped vs our 2;
official blocks the request vs our instant return; ours reconciles on boot vs their `pkill`+empty.

## Ideas SAFE and USEFUL to adopt
1. Rotating-counter port allocation with `socket.bind` probe (`official: browser_manager.py:364-377`)
   → replace our ad-hoc `_free_port()` (`ours: google_seed.py:58-63`).
2. Pre-launch stale-Singleton cleanup (`official: browser_manager.py:186-190`) → prevents "profile in
   use" after a hard kill; one-liner, no security impact.
3. Curated detection-test bookmark set (`official: browser_manager.py:83-114`) as a user-visible pref.
4. `--use-angle=swiftshader`/`--test-type` awareness for GPU-less diagnostic launches
   (`official: browser_manager.py:381-385`).
5. WebSocket origin-vs-Host check pattern (`official: main.py:89-136`) as reference if we add any WS
   surface (complements our CORS + install-token).

## Ideas to REJECT (incompatible with our model)
1. Plain-`Preferences` DSE write — the stealth binary rejects it as tampering.
2. Launching without proxy preflight — dead-proxy launches + loses exit-IP geo/WebRTC alignment.
3. Free-form proxy string through the launch layer — risks credential leakage (ours keyrings creds).
4. In-memory-only runtime state with no cross-process lock — reintroduces duplicate/orphan risk on a
   shared desktop.
5. Blocking the launch request until running — defeats our fast-return + background-worker model.
6. Relying on the Playwright `close` event — never fires in our unpumped worker loop.
7. Exposing a per-profile TCP CDP port + WS passthrough — a local attack surface we deliberately block.
