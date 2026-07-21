# Manager Browser Runtime Foundation Design

## Objective

Turn the existing profile start/stop placeholders into an owned Windows browser-runtime service. It launches each profile in its dedicated persistent data directory, prevents duplicate instances, tracks lifecycle state, streams safe events to the dashboard, and reconciles owned processes after manager restart.

The runtime foundation does not implement AI or page automation. Those systems may consume this runtime later through separately authorized interfaces.

## Concurrency Model

Each running profile has one dedicated `ProfileWorker` thread. The worker creates and owns its synchronous Playwright driver and persistent browser context, then processes control messages on the same thread. This avoids crossing Playwright thread boundaries and isolates a stalled browser from FastAPI request handling.

A central `RuntimeManager` owns worker registration, per-profile locks, the launch queue, and event publication. It permits many running profiles subject to machine resources, but only two profiles launch concurrently by default. `ManagerSettings.max_concurrent_launches` is configurable from 1 to 8. The limit controls launch work, not the number of already-running profiles.

One profile can have at most one active worker. Concurrent start requests for the same profile return `profile_already_running` or the existing `starting` state without creating another process.

## Persistent Profile Storage

Every profile receives a manager-owned directory below:

`%LOCALAPPDATA%\CloakBrowser\Manager\profiles\<profile-id>\user-data`

The backend resolves and validates this path; the frontend never supplies filesystem paths. A filesystem lock next to `user-data` prevents a second manager process from launching the same profile. Locks include manager instance ID, PID, process creation time, and profile ID, but no secrets.

Moving a profile to trash does not delete its data. Permanent purge is refused while the profile is running and removes the data only through a separately confirmed operation.

## Runtime Persistence

Migration adds `runtime_sessions`:

- `id`, `profile_id`, and unique active-profile constraint.
- `state`: `queued`, `starting`, `running`, `stopping`, `stopped`, `crashed`, or `detached`.
- Manager instance ID and manager PID/creation time.
- Browser PID/creation time when verified.
- Local CDP endpoint metadata when available; never an externally reachable address.
- `started_at`, `stopped_at`, `exit_code`, and sanitized `last_message`.

Profile API reads derive `runtime_state` from the current runtime session rather than returning constant `stopped`.

## Start Flow

`POST /api/v1/profiles/{id}/start` returns HTTP 202 with the runtime session in `queued` or `starting` state.

The runtime:

1. Authenticates the request and acquires the in-process profile lock.
2. Rejects trashed, missing, already active, or inconsistent profiles.
3. Acquires the filesystem lock.
4. Resolves the installed binary and verifies the profile's stored fingerprint configuration.
5. Resolves the profile-owned proxy and performs the mandatory bounded proxy preflight for non-direct mode. Proxy failure prevents launch.
6. Builds launch arguments from allowlisted profile fields, the stable fingerprint seed, consistent preset, proxy-aligned location settings, extensions, and startup URLs.
7. Creates a headed persistent context in the profile's `user-data` directory.
8. Records verified ownership metadata, opens startup URLs, emits `running`, and releases the launch semaphore.

Launch failures close partial resources, release both locks, and end in `crashed` with a safe code such as `binary_unavailable`, `profile_locked`, `proxy_preflight_failed`, or `browser_launch_failed`. Raw commands, credentials, authenticated URLs, Playwright exception text, and local paths are not returned to the frontend.

## Stop and Crash Flow

`POST /api/v1/profiles/{id}/stop` returns HTTP 202. It is idempotent when already stopped.

The manager sends a close command to the owning worker, which closes the persistent context and Playwright driver on its own thread. It waits up to 10 seconds. Escalation is permitted only for child processes whose PID, creation time, command line, and manager-owned user-data path all match the runtime record. It never kills a PID based only on a database value.

User-closing the browser window, browser crash, or worker exception updates the runtime row to `stopped` or `crashed`, releases locks, records accumulated runtime, and emits an event. Backend shutdown requests graceful closure but never deletes profile data.

## Restart Reconciliation

At manager startup, reconciliation examines sessions left in `queued`, `starting`, `running`, or `stopping`:

- If no verified owned process exists, mark the session `crashed` with `manager_restarted`.
- If an owned Chromium process and loopback CDP endpoint both verify, attempt to reconnect and create a replacement worker controller.
- If the process exists but cannot be safely controlled, mark it `detached`; show the owner a recovery action but do not terminate it automatically.
- Stale lock files are removed only after verifying the recorded PID and creation time no longer match a live manager/browser process.

Reconciliation emits one summary event and never silently launches a profile.

## Runtime API

- `POST /api/v1/profiles/{id}/start`
- `POST /api/v1/profiles/{id}/stop`
- `GET /api/v1/profiles/{id}/runtime`
- `GET /api/v1/runtime-sessions?state=...`

Future focus, restart, window arrangement, and browser automation commands build on the same worker command channel; they are not required for the first runtime milestone.

## Event Contract

Use authenticated WebSocket endpoint `/api/v1/events`. Authentication uses the existing session cookie; the exact configured Origin is mandatory during the WebSocket handshake. Tokens never appear in query strings.

Events use:

```json
{
  "event": "profile.runtime.changed",
  "sequence": 184,
  "timestamp": "2026-07-21T12:00:00Z",
  "data": {
    "profile_id": "uuid",
    "runtime_session_id": "uuid",
    "state": "running",
    "message_code": "ready"
  }
}
```

Events are safe invalidation/status hints. On connection or sequence gaps, the frontend refetches authoritative REST state. No event contains page content, URLs, credentials, command lines, filesystem paths, or exception text.

## Testing

Unit tests inject a `FakeBrowserLauncher`, fake process inspector, fake filesystem lock, and synchronous event sink. Normal tests launch no browser.

Coverage includes launch queue limits, one-instance enforcement, state transitions, worker-thread ownership, start/stop idempotency, partial-launch cleanup, mandatory proxy-preflight blocking, profile-data paths, safe errors, verified escalation, crash detection, restart reconciliation, WebSocket cookie/origin enforcement, monotonic event sequences, migration upgrade/downgrade, and OpenAPI schemas.

A separate `slow` Windows integration test launches a real profile, verifies its user-data persistence and PID ownership, stops it, restarts the manager, and exercises reconciliation. It is not part of the offline manager suite.
