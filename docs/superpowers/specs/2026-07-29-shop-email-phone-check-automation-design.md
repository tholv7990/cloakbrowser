# Shop Email Phone-OTP Check Automation — Design

**Date:** 2026-07-29  
**Status:** Approved for planning  
**Scope:** Local Plasma desktop manager; Windows profiles; authorized accounts only

## 1. Objective

Add a purpose-built automation that accepts authorized email addresses, creates temporary
CloakBrowser profiles, assigns a distinct 711Proxy sticky route to each profile, opens
`https://shop.app/`, submits up to five emails sequentially per profile, classifies the
resulting Shop login state, and exports accounts that require phone OTP.

The feature must not bypass CAPTCHA, obtain or submit OTP codes, reconstruct masked phone
numbers, or operate on accounts the user is not authorized to access.

## 2. Research and existing capabilities

Plasma already has the required low-level building blocks:

- Batch profile creation with a unique fingerprint seed per profile.
- Persistent per-profile user-data directories and startup URLs.
- Secure proxy credentials through `CredentialStore`.
- 711Proxy route generation in `features/proxies/providers.py`. It creates a unique
  `session-XXXXXXXX` directive per route and supports region targeting and sticky time.
- Proxy preflight and cached health information.
- Owned runtime launch/stop and bounded automation coordination.
- Automation credentials stored by reference rather than as plaintext in public schemas.

Competitor and upstream patterns support quantity-based batch creation, startup URLs,
per-profile proxy assignment, proxy testing before launch, persistent profile directories,
and bounded launch queues. The new feature should orchestrate Plasma's existing services;
it must not restore the retired generic Profile Factory.

## 3. User workflow

### Inputs

- A UTF-8 `.txt` file or pasted text containing one email per line.
- Target URL, fixed to `https://shop.app/` in v1.
- Proxy provider, fixed to configured 711Proxy in v1.
- Region: random by default, or a supported two-letter country code.
- Emails per profile: default 5, configurable 1–5.
- Maximum parallel profiles: default 3, configurable 1–5 in v1.
- Profile-name prefix and output directory.

Blank lines are ignored, email addresses are normalized for duplicate detection, and
duplicates are reported rather than processed twice. The number of worker profiles is
`ceil(valid_unique_emails / emails_per_profile)`.

### Execution

For each worker:

1. Generate one unique 711Proxy sticky route.
2. Preflight the route and record exit IP, country, timezone, and latency.
3. Retry generation with a new session up to the bounded proxy retry limit.
4. Create a uniquely seeded Windows profile owned by this automation run.
5. Assign the tested proxy and set Shop as the startup URL.
6. Launch through the bounded worker queue.
7. Process the worker's emails sequentially.
8. Reset Shop origin state between emails: cookies, local storage, session storage, cache
   where supported, extra tabs, and navigation back to the login URL.
9. Stop the worker after its assigned emails reach terminal results or the worker becomes
   unhealthy.

If a worker hits CAPTCHA, rate limiting, a failed proxy, or repeated unknown page states,
remaining assigned emails are not blindly submitted. They become retryable and may be
requeued onto a newly created worker.

## 4. Page interaction and classification

Use semantic DOM signals before text fallbacks. Support English and Vietnamese copy.
Selectors must be centralized and versioned. Screenshots are supporting evidence, not the
primary classifier.

Terminal email outcomes:

- `phone_otp_required`
- `email_otp_required`
- `login_success`
- `account_not_found`
- `captcha_or_challenge`
- `proxy_failed`
- `navigation_failed`
- `unknown`
- `cancelled`

`phone_otp_required` requires multiple agreeing signals where available: OTP inputs,
masked-phone text, and a phone-oriented verification heading/action. Store only visible
phone data:

- `phone_prefix`, such as `+84`
- `phone_suffix`, such as `027`
- `country_code` and `country_name` when the prefix is unambiguous
- `region_name` for shared plans such as `+1`/NANP
- `country_confidence`: `exact`, `ambiguous`, or `unknown`

Never infer the phone country from the proxy, and never reconstruct hidden digits.

## 5. State model

Run states:

`queued -> preparing -> running -> completed | completed_with_issues | cancelled | failed`

An email is complete only after reaching a terminal outcome. A run is:

- `completed` when every valid email has a terminal non-retryable outcome.
- `completed_with_issues` when every email is terminal but one or more are retryable
  failures, CAPTCHA, or unknown.
- Not complete while any email is pending, running, or waiting for an automatic retry.

Worker states:

`pending -> proxy_check -> profile_create -> launching -> processing -> stopping -> terminal`

Every transition is persisted. Aggregate counts are recomputed from item rows rather than
incremented optimistically, so retries and concurrent workers cannot double count.

## 6. Data ownership and cleanup

Do not identify temporary profiles using names or mutable tags alone. Persist an immutable
run-to-profile ownership row containing the exact profile ID and `automation_run_id`.
Existing manually created profiles and profiles from other runs are never eligible.

After all emails finish, show a persistent completion alert with:

- Result counts and retryable count.
- Temporary profile count and estimated disk use.
- `Retry failed`, `Export results`, `View profiles`, and
  `Delete all run profiles` actions.

Cleanup is manual. `Delete all run profiles`:

1. Requires explicit confirmation and displays exact owned profile count.
2. Stops any owned runtime still active.
3. Hard-deletes only profile IDs owned by that run.
4. Safely removes only their contained profile directories.
5. Preserves run results and exported files.
6. Does not delete manually created profiles, profiles from other runs, or proxy records.
7. Is resumable and reports partial failures per profile.

The cleanup API accepts only a run ID. It resolves owned profile IDs server-side and never
accepts arbitrary filesystem paths or a client-supplied list of profile IDs.

## 7. Persistence

Use dedicated tables rather than the retired `ProfileFactoryJob` models:

- `shop_check_runs`: configuration, state, counters, timestamps, export/cleanup state.
- `shop_check_emails`: normalized-email fingerprint, secure email reference, ordinal,
  result, visible phone metadata, retry count, worker ID, timestamps, sanitized error.
- `shop_check_workers`: run ID, owned profile ID, generated proxy ID, ordinal, state,
  assigned count, processed count, sanitized error.

Full email values belong in `CredentialStore`. The database stores a credential reference,
SHA-256 fingerprint, and result metadata. API list responses may return the email only when
needed by the authenticated local operator for this explicit workflow; otherwise return a
masked value. Neither logs nor error messages may contain full emails or proxy secrets.

Add explicit indexes on run/status/order and ownership lookup. Add a real migration and a
startup schema-compatibility check; do not rely on `Base.metadata.create_all()` to add
columns to an existing database.

## 8. API contract

All routes use `/api/v1`, `StrictModel(extra="forbid")`, existing session/origin/CSRF
protection, unique operation IDs, and maintenance guards for mutations.

Suggested endpoints:

```text
POST   /api/v1/automations/shop-check/runs
GET    /api/v1/automations/shop-check/runs
GET    /api/v1/automations/shop-check/runs/{run_id}
POST   /api/v1/automations/shop-check/runs/{run_id}/cancel
POST   /api/v1/automations/shop-check/runs/{run_id}/retry
GET    /api/v1/automations/shop-check/runs/{run_id}/export.csv
GET    /api/v1/automations/shop-check/runs/{run_id}/phone-otp.txt
POST   /api/v1/automations/shop-check/runs/{run_id}/cleanup
```

Create accepts write-only email text, run settings, and output preferences. The response
never echoes proxy credentials. Run detail contains aggregate counts, worker progress, and
paginated/masked email results.

## 9. Export

CSV is authoritative:

```csv
email,result,phone_prefix,country,country_code,region,phone_suffix,confidence,profile_id,checked_at
```

An optional TXT export contains only deduplicated full emails whose result is
`phone_otp_required`. Exports are written atomically through a temporary file and replace,
with CSV-injection protection for spreadsheet-interpreted values. The API may also stream
the export without persisting it.

## 10. Frontend

Add a `Shop check` tab or workflow within Automation:

- Creation wizard with email validation summary and computed profile count.
- 711 configuration/region check and concurrency settings.
- Live aggregate summary plus worker and email-result tables.
- Filters for phone OTP, email OTP, CAPTCHA, failures, and unknown.
- Completion banner with retry/export/view/cleanup actions.
- Destructive cleanup confirmation with exact scope.

The UI must make clear that five emails share one profile/fingerprint/IP and that the
workflow is for authorized accounts only.

## 11. Failure and recovery

- Startup recovery marks interrupted running workers as recoverable and stops/reconciles
  owned runtimes.
- Retries are bounded and idempotent.
- A retry never overwrites an earlier terminal result without recording an attempt.
- Cancellation stops scheduling new emails, stops run-owned workers, and persists remaining
  items as cancelled.
- One worker failure cannot fail unrelated workers.
- Shop DOM changes produce `unknown` plus sanitized diagnostics, not false phone matches.

## 12. Test strategy

- Unit fixtures for every English/Vietnamese classifier outcome and near-miss.
- Phone-prefix tests including `+84`, `+44`, ambiguous `+1`, masked/invalid values.
- Coordinator tests for grouping 0/1/5/6/100 emails, bounded concurrency, cancellation,
  recovery, retries, and aggregate recomputation under races.
- Proxy tests proving distinct 711 session directives and secret non-disclosure.
- Cleanup tests proving cross-run and manual profiles survive, active owned profiles stop,
  path containment is enforced, and partial deletion is resumable.
- API tests for auth, CSRF/origin, strict schemas, pagination, export injection, and secret
  leakage.
- Frontend tests for computed profile count, progress, completed-with-issues, export, and
  exact-scope cleanup confirmation.
- Contract gate: regenerate OpenAPI and require a clean diff.
- No real Shop requests in the default test suite; use deterministic local HTML fixtures.

## 13. Explicit non-goals

- CAPTCHA bypass.
- OTP retrieval, guessing, or submission.
- Checking unauthorized or third-party accounts.
- Reconstructing masked phone numbers.
- Per-request IP rotation during one email flow.
- Automatic deletion at run completion.
- Deleting generated proxy records during profile cleanup.
- General-purpose profile factory resurrection.

