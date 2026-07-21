# Profile-Owned Proxy Design

> Superseded by `2026-07-21-manager-proxy-management-design.md`. The implemented frontend requires a reusable Proxy Manager plus create/edit/assign actions inside profile workflows. Profiles therefore reference shared proxy records by `proxy_id`.

## Decision and Competitor Evidence

CloakBrowser version 1 stores one proxy configuration as part of each browser profile. It does not provide a separate proxy inventory, reusable proxy records, proxy paging, or assignment workflow.

This follows BitBrowser's core profile model: its official profile API includes proxy fields and a batch profile-proxy update endpoint. GoLogin also defines a proxy connection as part of each profile, while offering an additional Proxy Manager for its larger cloud/provider product. CloakBrowser is a local single-user manager, so GoLogin's extra shared inventory would add complexity without a current requirement.

Sources reviewed July 21, 2026:

- BitBrowser browser-profile API: https://doc.bitbrowser.net/api-docs/browser-profiles
- BitBrowser add-profile guide: https://doc.bitbrowser.net/help1/browser-profiles/add-a-new-browser-profile
- GoLogin profile settings: https://support.gologin.com/en/articles/14854406-profile-settings
- GoLogin proxy management: https://support.gologin.com/en/articles/14810002-adding-and-managing-proxies

## Profile Data

Each profile contains a nullable `proxy_config_json` object:

- `mode`: `direct`, `http`, `https`, `socks5`, or `socks5h`.
- `host` and `port`, absent for `direct` and required otherwise.
- `credential_ref`, an opaque UUID reference stored only in this private database object and never returned by the API.
- `username_present`, computed for safe reads rather than trusted from writes.
- `test_before_launch`, default `true`.
- Safe cached quick-test data: state, exit IP, country, region, city, timezone, ASN, organization, median latency, and checked timestamp.

The existing top-level `proxy_id` field is removed. Profile reads expose a safe `proxy` object with mode, masked endpoint, `username_present`, test-before-launch, and cached test metadata. They never expose `credential_ref`, username, password, or an authenticated URL.

## Credential Storage

Python `keyring` stores credentials in Windows Credential Manager under service `cloakbrowser-manager-profile-proxy`. The account name is the random `credential_ref`; the secret is compact JSON containing username and password.

Profile create and update accept write-only `proxy.username` and `proxy.password`; both must be supplied together. Omitting both on update preserves the current credential. `proxy.clear_credentials=true` removes it and cannot accompany new credentials. Switching to `direct` removes any stored credential after the database update succeeds.

Credential-store and database changes use compensating cleanup. Failures return the safe `credential_store_unavailable` HTTP 503 error without provider exception text or secrets.

## Create, Edit, Duplicate, and Remove

Proxy fields are accepted inside normal profile create and patch requests. The profile editor's Proxy section saves through the existing profile endpoints; there is no proxy CRUD API.

Duplicating a profile copies the proxy network settings but does not copy its credential by default. The duplicate response reports `proxy_credentials_required=true` when the source used credentials, so the owner must enter them for the new profile. This avoids silently creating multiple identities that share a sensitive endpoint credential. A later explicit duplicate option may add credential copying if demanded.

Removing a proxy uses `PATCH /api/v1/profiles/{id}` with `proxy.mode=direct`. Deleting a profile removes its Credential Manager entry only when the profile is permanently purged; moving it to trash preserves the credential for restoration.

## Parse and Test Endpoints

- `POST /api/v1/profiles/proxy/parse` parses an unsaved editor value without persistence.
- `POST /api/v1/profiles/{id}/proxy/quick-test` performs a synchronous bounded test and caches safe metadata on that profile.
- `POST /api/v1/profiles/{id}/proxy/quality-test` creates an asynchronous diagnostic run and returns HTTP 202.
- `GET /api/v1/profiles/{id}/proxy/reports` lists sanitized quality summaries.
- `GET /api/v1/proxy-reports/{run_id}` returns a safe report and manager-owned artifact links.

Bulk proxy assignment follows Hidemium's efficient selected-profile workflow while keeping proxy data owned by profiles:

- `POST /api/v1/profiles/proxy/bulk-preview` parses up to 100 pasted proxies and returns masked profile-to-proxy mappings plus safe validation errors.
- `POST /api/v1/profiles/proxy/bulk-apply` applies explicit profile/proxy pairs and returns per-profile successes and failures.

One proxy can be applied to all selected profiles only after a linkage warning. Equal profile/proxy counts map sequentially by the explicit selected-profile order. Fewer proxies never repeat silently; round-robin reuse requires an explicit option. More proxies report unused input lines before apply.

The parser supports official competitor-style formats plus CloakBrowser schemes: URLs, `host:port`, `host:port:username:password`, `username:password@host:port`, and bracketed IPv6 URLs. Bare values default to SOCKS5. It rejects paths, queries, fragments, control characters, partial credentials, invalid ports, and ambiguous unbracketed IPv6.

## Quick Test

Quick Test resolves the profile credential in memory and reuses the existing proxy connectivity/intelligence code. It records two-service exit-IP agreement, three-request median latency, location, timezone, ASN, and organization with a 20-second total budget.

Failures map to safe categories: `authentication_failed`, `connection_refused`, `timeout`, `dns_failed`, or `upstream_unavailable`. Credentials, raw parse input, and authenticated URLs never appear in logs, responses, SQLite, or artifacts.

## Quality Test

Quality Test reuses `benchmarks.proxy_quality` asynchronously with its credential-safe loopback relay and temporary browser profile. It keeps network type separate from reputation and records selected abuse-list evidence, WebRTC/DNS/timezone/locale alignment, one Google observation, and one Cloudflare Turnstile-demo observation. It never solves or interacts with a CAPTCHA.

Only one active quality run is allowed per profile. Manager restart marks orphaned queued/running jobs failed with `manager_restarted`. Reports retain the scanner's timestamped `clean_observed` disclaimer and never claim permanent cleanliness.

## Launch Behavior

The runtime adapter resolves the profile's proxy just before launch. `direct` produces no proxy argument. Other modes use CloakBrowser's existing resolver. SOCKS5H is recommended for remote DNS; SOCKS5 retains local DNS delegation semantics.

When `test_before_launch` is enabled, launch performs the bounded connectivity stage. Authentication or connection failure blocks launch with a safe error. Reputation alone never blocks launch automatically.

## Security and Verification

All endpoints require owner authentication, and mutations require exact Origin and CSRF. Tests use an in-memory credential store and injected offline network/quality adapters.

Automated coverage includes parser formats, schema secrecy, create/edit/duplicate/direct transitions, smart bulk mapping/partial failures, keyring compensation, trash behavior, quick-test caching/error mapping, quality lifecycle, migration upgrade/downgrade, OpenAPI write-only inputs, and existing proxy-scanner regressions.
