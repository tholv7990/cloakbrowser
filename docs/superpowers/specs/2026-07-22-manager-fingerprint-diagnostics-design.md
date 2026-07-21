# Manager Fingerprint Diagnostics and Pixelscan

## Scope

Add persisted, asynchronous browser diagnostics for a selected profile and a direct-network control. The feature measures observable results; it does not claim permanent invisibility, bypass CAPTCHAs, or modify a profile automatically.

## Data model

Create `diagnostic_runs` with UUID, nullable profile ID, kind, status, target URL, requested/started/completed timestamps, normalized progress, summary, findings JSON, screenshot path, report path, safe error code, and safe error message. Kinds are `direct_google_control`, `pixelscan`, `iphey`, `cloudflare`, and `google_search`. Statuses are `queued`, `running`, `passed`, `warning`, `failed`, and `cancelled`.

Only one active diagnostic per profile is allowed. The manager recovers orphaned queued/running rows as failed on startup. Reports live below `<data_root>/diagnostics/<run-id>` and paths are exposed only after root-containment checks.

## API and events

- `GET /api/v1/diagnostics` with profile, kind, status, page, and page-size filters
- `GET /api/v1/diagnostics/{id}`
- `POST /api/v1/diagnostics/direct-google-control`
- `POST /api/v1/diagnostics/pixelscan` with `profile_id`
- `POST /api/v1/diagnostics/iphey` with `profile_id`
- `POST /api/v1/diagnostics/cloudflare` with `profile_id`
- `POST /api/v1/diagnostics/google-search` with `profile_id` and a harmless fixed query
- `POST /api/v1/diagnostics/{id}/cancel`

Creation returns HTTP 202. Workers publish `diagnostic.progress` and `diagnostic.completed`. Progress is bounded 0–100 and event payloads contain no page HTML, cookies, credentials, or arbitrary exception text.

## Execution

Profile diagnostics require the profile to be stopped and reuse its exact launch builder: fingerprint seed/config, proxy, GeoIP, window, behavior, and enabled extensions. The control uses a temporary manager-owned profile, no proxy, and the same installed CloakBrowser tier/version. Proxy preflight runs before profile diagnostics and a failed proxy produces a diagnostic failure without launching.

Each runner navigates only to an allowlisted HTTPS target, waits for stable page state with bounded timeouts, records final URL/title and a screenshot, and extracts a small allowlisted set of visible result labels. Raw DOM, page source, storage, and network bodies are not persisted. A JSON report records browser tier/version, profile fingerprint revision/hash, proxy test timestamp/classification without endpoint credentials, target, timings, findings, and limitations.

Pixelscan findings normalize consistency, automation, browser, hardware, location, and overall result. IPhey normalizes browser/location/hardware/privacy sections. Cloudflare records whether the test page loaded, whether a managed challenge appeared, and whether user interaction is required. Google Search records page load, consent/interstitial, unusual-traffic/CAPTCHA detection, and result visibility. CAPTCHA presence sets `warning` with `captcha_user_action_required`; automation stops and never clicks or solves it.

## Frontend

The Diagnostics page uses real API data, profile and test selectors, queued/running progress, result cards, history filters, safe error copy, and links to manager-owned artifacts. It clearly distinguishes direct control from profile/proxy results and displays the observation timestamp.

## Failure handling

Network, timeout, proxy, browser crash, target-layout change, and CAPTCHA conditions map to stable safe codes. Cancellation closes the owned temporary browser and marks the run cancelled. Worker shutdown always releases concurrency slots and temporary profiles.

## Verification

Unit tests use local deterministic fixture pages and injected runner adapters, not public sites. They cover state transitions, concurrency, proxy preflight, allowlists, normalization, sanitization, CAPTCHA pause behavior, cancellation, orphan recovery, artifact containment, events, OpenAPI, and frontend rendering. A separately marked live test exercises public targets only when explicitly run.
