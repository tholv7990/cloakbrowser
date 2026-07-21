# Manager Proxy Management Design

## Objective

Add secure reusable proxy records to the local Windows profile manager. The owner can create, parse, edit, assign, test, and delete Direct, HTTP, HTTPS, SOCKS5, and SOCKS5H configurations without placing credentials in SQLite, API responses, logs, command lines, or report artifacts.

The manager reuses the existing `benchmarks.proxy_quality` scanner and its trusted intelligence adapters. It does not add CAPTCHA solving or challenge bypass behavior.

## Proxy Records

A proxy record contains:

- `id`, UUID string.
- `label`, required and unique after case-insensitive trimming.
- `scheme`: `direct`, `http`, `https`, `socks5`, or `socks5h`.
- `host` and `port`; both are absent for `direct` and required otherwise.
- `username_present`, derived from the credential store rather than accepted as authoritative input.
- `credential_ref`, an opaque UUID reference, never returned by the API.
- `test_before_launch`, default `true`.
- Safe cached test fields: exit IP, country, region, city, timezone, ASN, organization, network type, confidence, reputation, median latency, last checked timestamp, and last test state.
- `created_at`, `updated_at`, and nullable `deleted_at`.

Profiles continue storing only `proxy_id`. A direct profile may leave `proxy_id` null or reference a reusable `direct` record. Soft-deleted proxies cannot be assigned or launched.

## Credential Storage

Use Python `keyring` with Windows Credential Manager. The keyring service name is `cloakbrowser-manager-proxy`; the account name is the random `credential_ref`. The stored secret is a JSON object containing the username and password.

SQLite never stores either credential. API reads expose only `username_present`. Create and update requests accept write-only `username` and `password`; both must be supplied together. Omitting both during update preserves the existing credential. `clear_credentials=true` removes it and cannot be combined with new credentials.

Database and credential changes use compensating cleanup:

- If keyring storage fails, no database change is committed.
- If database creation fails after storing a new keyring secret, the new secret is deleted.
- Replacing credentials stores the new secret first, commits the database reference, then deletes the old secret.
- Deleting a proxy removes its credential only after the database operation succeeds.

Keyring failures return `credential_store_unavailable` with HTTP 503 and never include provider exception text.

## Parsing and Validation

`POST /api/v1/proxies/parse` accepts one write-only text value and returns normalized editable fields without saving them. Supported inputs:

- `http://user:password@host:port`
- `https://host:port`
- `socks5://user:password@host:port`
- `socks5h://host:port`
- `host:port`
- `host:port:username:password`
- `username:password@host:port`
- Bracketed IPv6 URL forms such as `socks5://[2001:db8::1]:1080`

Bare inputs default to SOCKS5 because that matches the manager's primary proxy workflow. URL credentials are percent-decoded exactly once. Hosts are normalized without DNS resolution. Ports must be 1–65535. Control characters, whitespace inside hosts, paths, queries, fragments, missing credential halves, and ambiguous unbracketed IPv6 are rejected.

The parser response may echo the submitted password only to the authenticated caller for immediate form population. The parse endpoint is the sole response exception to credential omission: its sensitive response is never cached, logged, placed in examples, or persisted. Saved proxy reads and test/report responses never return credentials. Create and update request password fields are marked write-only in OpenAPI.

## CRUD API

- `GET /api/v1/proxies`: paginated/filterable list with assigned-profile counts.
- `POST /api/v1/proxies`: create a record and optional credential.
- `GET /api/v1/proxies/{id}`: safe record details.
- `PATCH /api/v1/proxies/{id}`: update metadata and optionally replace or clear credentials.
- `DELETE /api/v1/proxies/{id}`: soft-delete only when no active or trashed profile references it.
- `POST /api/v1/proxies/parse`: parse without persistence.

Deleting a referenced proxy returns `proxy_in_use` with HTTP 409 and its safe assigned-profile count. The owner must reassign those profiles first. List search matches label, host, exit IP, country, city, ASN, and organization. Sorting uses an allowlist and page size is 1–100.

## Quick Test

`POST /api/v1/proxies/{id}/quick-test` performs a bounded non-browser check and returns synchronously. It resolves the proxy credential in memory, builds the upstream URL, and calls the scanner's connectivity and structured location/ASN adapters.

It records:

- Connection success or a safe failure category.
- Exit IP from two independent echo services and whether they agree.
- Median latency from three lightweight requests.
- Country, region, city, timezone, ASN, and organization when available.
- Test timestamp.

The total request budget is 20 seconds. Network/provider error strings are mapped to safe categories such as `connection_refused`, `authentication_failed`, `timeout`, `dns_failed`, or `upstream_unavailable`. Credentials and reconstructed authenticated URLs never enter logs, responses, or SQLite.

## Quality Test

`POST /api/v1/proxies/{id}/quality-test` creates an asynchronous diagnostic run and returns HTTP 202 with a run ID. Only one active quality run is allowed per proxy. The worker reuses `benchmarks.proxy_quality` in process with a dedicated temporary browser profile and the existing credential-safe loopback relay.

The scan keeps network classification and reputation separate and includes connectivity, selected trusted abuse lists, WebRTC/DNS/timezone/locale alignment, one Google Search observation, and one Cloudflare Turnstile demo observation. It never attempts to solve or interact with a CAPTCHA.

`GET /api/v1/proxies/{id}/reports` lists sanitized summaries. `GET /api/v1/proxy-reports/{run_id}` returns the safe report and artifact links under the manager-owned diagnostics directory. Reports state that `clean_observed` is timestamped evidence, not a permanent guarantee.

Quality runs have states `queued`, `running`, `completed`, `failed`, or `cancelled`. Manager restart marks orphaned `queued`/`running` jobs failed with `manager_restarted`; it does not silently restart live-site checks.

## Profile Launch Integration

Before launch, the runtime adapter resolves the selected record and its credential in memory. `direct` produces no proxy argument. Other schemes are passed through the existing CloakBrowser proxy resolver. SOCKS5H is recommended when remote DNS delegation is required; plain SOCKS5 intentionally retains local DNS delegation semantics.

When `test_before_launch` is enabled, the manager runs the bounded quick connectivity stage. Launch stops on connectivity or authentication failure and returns a safe error. A questionable reputation result does not block launch automatically.

## Security and Privacy

- Every route requires the owner session; every mutation requires exact Origin and CSRF.
- Proxy credentials are redacted before logging and excluded from audit details.
- API validation errors must not echo the raw parse string or password.
- Reports and screenshots contain no authenticated endpoint or credential.
- Tests use an in-memory fake credential store and mocked network adapters; normal manager tests require neither network access nor Windows Credential Manager.

## Verification

Automated tests cover parsing formats and rejection cases, keyring compensation, safe CRUD reads, reference-aware deletion, credential redaction, quick-test caching/error mapping, quality-run lifecycle, authentication/CSRF, migration upgrade/downgrade, and OpenAPI write-only fields. Existing proxy scanner tests remain the source of truth for intelligence, browser relay, Google, and Cloudflare classification behavior.
