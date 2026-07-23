# Cloud data model

**Status:** implemented (`cloud/models.py`, `cloud/db.py`, `cloud/keys.py`) + tested
(`tests/cloud/test_data_model.py`, 6 green). PostgreSQL in prod, SQLite in tests; types kept
portable. Design rules: **no secret in plaintext**, and **race-safety enforced by constraints**, not
just app code.

## Tables

| Table | Key columns | Notes |
|---|---|---|
| `users` | `id`, `email` (unique), `password_hash` (argon2id), `status` | email normalized (trim+lower) → case-insensitive uniqueness portably; `status ∈ {unverified,active,suspended}` (CHECK) |
| `email_verifications` | `user_id`→users, `token_hash` (unique), `expires_at`, `consumed_at` | stores **SHA-256** of the emailed token, never the token |
| `password_resets` | `user_id`→users, `token_hash` (unique), `expires_at`, `consumed_at` | same token-hash discipline |
| `devices` | `id`, `user_id`→users, `public_key`, `revoked_at`, `last_seen_at` | Ed25519 device **public** key; `unique(user_id, public_key)`; `index(user_id, revoked_at)` for the device-limit count |
| `sessions` | `user_id`, `device_id`, `family_id`, `refresh_token_hash` (unique), `rotated_at`, `revoked_at`, `reuse_detected_at` | refresh **hash** only; rotation family; reuse → revoke family |
| `plans` | `id` (`solo`/`pro`), `max_devices`, `max_profiles`, `max_sessions`, `features` (JSON) | the entitlement limits |
| `activation_keys` | `id`, `verifier` (unique), `lookup_prefix`, `last4`, `plan_id`→plans, `max_uses`, `uses_remaining`, `expires_at`, `status` | **HMAC verifier only**; `uses_remaining>=0` (CHECK); `status ∈ {active,suspended,revoked}` |
| `redemptions` | `id`, `key_id`→keys, `user_id`, `device_id` (NOT NULL) | **`unique(key_id, device_id)`** = per-device **idempotency**; the total use cap is the atomic `uses_remaining` decrement in the redeem tx (below), not this constraint |
| `entitlements` | `id`(=jti), `user_id`, `device_id`, `key_id`, `plan_id`, `issued_at`, `expires_at`, `offline_grace_deadline`, `version`, `revoked_at` | record of each issued signed entitlement (for audit + revocation) |
| `subscriptions` | `user_id`, `plan_id`, `status`, `current_period_end`, `provider`, `provider_ref` | optional for v1; billing attaches later without a schema break |
| `audit_events` | `ts`, `actor`, `action`, `subject_type`, `subject_id`, `data` (JSON) | append-only; **non-secret** metadata only; `index(ts)`, `index(subject_type,subject_id)` |
| `update_releases` | `channel`, `version`, `min_supported_version`, `artifact_url`, `sha256`, `signature`, `published_at` | `unique(channel, version)`; `channel ∈ {stable,beta}` (CHECK); signed update metadata |

## What is NOT here (by design)

No column anywhere holds a raw password, activation key, refresh/verification/reset token, proxy
password, cookie, or any browser data. Every credential is a **hash or keyed verifier**; browser data
never leaves the desktop (see [local-data-ownership.md](local-data-ownership.md)).

## Race-safety (schema-enforced)

- **Redemption:** two layers. (1) `unique(redemptions.key_id, device_id)` with `device_id` **NOT
  NULL** = per-device idempotency (a retried redeem can't double-consume; proved by
  `test_one_time_key_cannot_be_double_redeemed`). (2) The **total** use cap across devices is an
  atomic guarded decrement in the redeem transaction —
  `UPDATE activation_keys SET uses_remaining = uses_remaining - 1 WHERE id=:id AND uses_remaining > 0`
  (check rowcount), inside a `SELECT … FOR UPDATE` on the key row. The unique constraint alone does
  **not** cap multi-device redemption — that's the decrement's job. (A Postgres-backed concurrency
  test is a follow-up; SQLite ignores row locks.)
- **Device/session identity:** `unique(devices.user_id, public_key)` and
  `unique(sessions.refresh_token_hash)` → idempotent device re-registration, and a rotated refresh
  can't be re-inserted.
- **Non-negative uses:** `CHECK(uses_remaining >= 0)` backs the decrement.

## Indexes (why each exists)

- `ix_devices_user_active(user_id, revoked_at)` — the plan device-limit count.
- `ix_sessions_family(family_id)`, `ix_sessions_user_active(user_id, revoked_at)` — reuse-revoke a
  family; list a user's live sessions.
- `ix_activation_lookup_prefix(lookup_prefix)` + `unique(verifier)` — support lookup by prefix;
  constant-time redeem lookup by verifier.
- `ix_entitlements_user_device`, `ix_audit_ts`, `ix_audit_subject`, `ix_releases_channel_published`
  — the common read paths.

## Activation key format (`cloud/keys.py`)

`PLASMA-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX` — 24 Crockford Base32 symbols = **120 bits**, excludes
ambiguous I/L/O/U; normalization maps lenient letters (O→0, I/L→1, U→V) so a human retype still
verifies. Stored as `HMAC-SHA256(server_pepper, normalized_key)`; only `lookup_prefix` (first group)
and `last4` are kept for support — the middle 16 symbols exist **only** inside the HMAC, so the key is
unrecoverable from a DB leak (proved by `test_activation_key_row_never_stores_the_raw_key`).

## Retention (recommendation)

- `email_verifications` / `password_resets`: delete consumed/expired rows after 30 days.
- `sessions`: keep revoked/expired for 90 days (audit), then purge.
- `audit_events`: retain ≥1 year (append-only; archive to cold storage beyond that).
- `entitlements`: keep while the device is active + 90 days.
- `update_releases`: keep all (small; needed for downgrade/version-floor decisions).

## Schema evolution

Managed by **Alembic** (to add next, mirroring the desktop's `manager_backend` discipline —
`env.py` targeting `cloud.db.Base.metadata`). Tests build via `create_all` for speed; production
migrates via `alembic upgrade head`.
