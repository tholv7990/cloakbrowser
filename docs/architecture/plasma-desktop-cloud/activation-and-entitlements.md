# Activation keys & entitlements

**Status:** design. How Plasma turns a purchased **activation key** into a signed, bounded
**entitlement** the desktop can verify offline — and how that stays strictly separate from the
**CloakBrowser engine licence** (a different secret, with a real legal blocker).

An activation key is **not** a permanent client API secret. It is redeemed once for a signed
entitlement; the key itself is never used as a long-lived token.

## Activation-key lifecycle

### Generation (recommendation)

- **160 bits of CSPRNG** (`secrets.token_bytes(20)`), encoded **Crockford Base32** (case-insensitive,
  no ambiguous 0/O/1/I), grouped for readability, with a trailing **check symbol** (mod-37) for
  typo detection:
  `PLASMA-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-C` (25 base32 chars ≈ 125 bits shown + check).
- **Assess the sample `PLASMA-XXXX-XXXX-XXXX-XXXX`:** 16 base32 chars = **80 bits**. 80 bits is
  un-guessable online *with* redemption rate-limiting, but there's no reason to skimp — go to
  **≥128 bits**. Recommendation above gives that plus a check symbol.

### Storage (never plaintext)

- Store only a **keyed verifier**: `verifier = HMAC-SHA256(server_pepper, normalized_key)`. HMAC (not
  a slow hash) is right here because the key is already high-entropy — it allows an **indexed,
  constant-time lookup** by verifier. The `server_pepper` lives in the server's secret manager, not
  the DB, so a DB leak alone can't reverse keys.
- Row also stores non-secret support fields: `key_id` (uuid), `lookup_prefix` (first group, e.g.
  `PLASMA-XXXXX`), `last4`, `plan`, `max_devices`, `max_profiles`, `max_sessions`, `features`,
  `expires_at`, `status`, `created_by`, `created_at`.
- **The raw key is shown exactly once at creation and never returned again.** It is never committed,
  never logged, never stored in plaintext.

### Redemption (one-time / limited, race-safe)

```mermaid
sequenceDiagram
  participant App
  participant API as Cloud
  App->>API: POST /activation/redeem {key, device_id} (authenticated)
  API->>API: verifier=HMAC(pepper,key); look up row
  API->>API: BEGIN; SELECT ... FOR UPDATE (row lock)
  API->>API: check status=active, not expired, uses_remaining>0
  API->>API: INSERT redemption (unique on key_id[,device]) ; decrement uses
  API->>API: COMMIT  %% unique constraint makes a double-redeem fail atomically
  API-->>App: signed entitlement (below)
```

Race safety: a `SELECT ... FOR UPDATE` around the check-and-decrement, plus a **unique constraint** on
`redemptions(key_id)` (or `(key_id, device_id)` for multi-device keys), so two concurrent redeems
can't both win. Reusing a spent one-time key returns a clean `already_redeemed`.

### States & admin

`active → suspended → revoked`; `expired` by time; `renew` extends `expires_at`. Every
create/redeem/suspend/revoke writes an **audit event**. **Support lookup never shows the full key** —
only `lookup_prefix` + `last4` (or `key_id`).

## Entitlement document

After redemption (and on each refresh) the server returns a **signed entitlement** — an EdDSA JWT (or
COSE) signed with the cloud's **Ed25519 private key**, carrying only **non-secret** claims:

```json
{
  "sub": "<account_id>", "device_id": "<device_id>", "plan": "pro",
  "features": ["media","automation","shopify_builder"],
  "profile_limit": 100, "session_limit": 10,
  "iat": 1700000000, "exp": 1700086400,
  "offline_grace_deadline": 1700604800,
  "entitlement_version": 3, "key_id": "<uuid>", "jti": "<uuid>"
}
```

### How the desktop validates it

1. Verify the **EdDSA signature** with the cloud **public key pinned in the app** (public, not a
   secret → satisfies "no permanent secret embedded").
2. `exp` not passed (or within `offline_grace_deadline` — see offline mode).
3. `device_id` == the local device (see [device-identity.md](device-identity.md)).
4. `entitlement_version` ≥ the app's minimum (forces refresh after a policy change).
5. Gate UI/features on `features`/`plan`; enforce `profile_limit`/`session_limit` locally.

The app **must not** trust an entitlement merely because it sits in local SQLite — validity is the
**signature + device + expiry**, re-checked each launch. Enforcement is layered/best-effort (a
patched client can lie), so the server independently enforces device/session limits at refresh.

### Revocation

- Short `exp` (≤24 h) forces periodic refresh; at refresh the server checks key status + device
  status + subscription → a revoked key/device **stops issuing** entitlements.
- Optional **revocation list** (`jti`/`device_id`) the desktop checks at refresh for fast kill.
- Online: revocation bites within the access-token/entitlement lifetime. Offline: bounded by the
  grace deadline; on reconnect a revoked state overrides any cached grace immediately.

## Device limits

Enforced **server-side** at issue/refresh: count active `devices` for the account vs
`plan.max_devices`; over the limit → refuse to issue for a new device (offer "replace a device").
Client-side counts are advisory only.

## Offline grace

Summarized here; full policy in [offline-mode.md](offline-mode.md): a cached, signed entitlement keeps
the app usable through a temporary outage up to `offline_grace_deadline` (recommend **7 days**); after
that, **launches lock** but existing profiles/backups/export remain available — never destructive.
Clock-rollback is detected via a stored monotonic "last seen server time."

---

## CloakBrowser licence separation — the Critical blocker

**Plasma activation keys and CloakBrowser engine licence keys are different secrets.** This section is
grounded in the repo audit (cited), not assumption.

### Confirmed facts

- The engine binary is **proprietary** and its redistribution terms are in-repo: you may **not**
  redistribute/resell/repackage it or "include it in any product or service distributed to third
  parties, except under a separate license" (`BINARY-LICENSE.md:67-70`). A **separate OEM/SaaS
  licence is required** when the binary is "bundled, embedded, exposed through an API, or used to
  provide browser functionality to third-party customers … as part of a product, hosted service,
  browser-as-a-service offering, or customer-facing workflow" (`BINARY-LICENSE.md:93,95`).
- The only in-repo-sanctioned model: **each end user's machine downloads the binary from official
  CloakHQ channels** and supplies their **own, non-shareable** key (`BINARY-LICENSE.md:91,101-103,55-57`).
- The engine needs the **raw key locally at runtime**: resolved arg → `CLOAKBROWSER_LICENSE_KEY` env
  → `~/.cloakbrowser/license.key` (`license.py:96-130`); the raw key is sent to CloakHQ for
  validation (`license.py:221-225`), for the Pro download (`download.py:456`), and **injected into
  the child browser process env** so the binary self-enforces (`license.py:139-202`).
- Enforcement lives in the **binary**, not the wrapper: exit code **76** = "session limit reached …
  close another running session or upgrade" (`license.py:52-69`) → per-active-**concurrent-session
  (seat)** licensing, validated against CloakHQ's server. Free tier = the pinned
  `CHROMIUM_VERSION` 146 (`config.py:18`); latest-major requires a paid subscription
  (`BINARY-LICENSE.md:25`).

### Implications

1. **Embedding one universal engine key is forbidden** — technically (the desktop is inspectable) and
   contractually (keys are non-shareable, `BINARY-LICENSE.md:55-57`). Never do it.
2. **Plasma cannot broker a device-bound engine token today** — the binary reads a *raw* key from its
   env; there is no CloakHQ token-exchange protocol in the wrapper. Such a flow would require CloakHQ
   to build/authorize it. **Blocker if that model is wanted.**
3. Plasma's own `session_limit` entitlement must be **reconciled** with the engine plan's seat cap —
   two independent limits; the stricter wins, and Plasma cannot exceed the engine's.

### Recommended model (v1)

- **Plasma entitlement = the *product* licence** (Plasma features + local limits), signed by Plasma's
  cloud. Independent of the engine.
- **Free engine only for v1** (pinned 146), auto-downloaded per-user from CloakHQ (no key). For **Pro
  engine** features, the customer **brings their own CloakBrowser key**, stored locally in
  DPAPI/Credential Manager, **never** sent to Plasma's cloud and **never** embedded.
- The engine binary is **never bundled or modified**; verification (`download.py` Ed25519→SHA256) is
  untouched.

### Before selling (hard gate)

- [ ] **CloakHQ written agreement** (`info@cloakbrowser.dev`): either confirm per-user auto-download of
  the free engine within a commercial Plasma product is permitted, or obtain an **OEM/SaaS licence**.
  Providing "browser functionality to third-party customers" plausibly triggers OEM even for the free
  engine (`BINARY-LICENSE.md:93,95`) — a **legal question**, not resolvable from source.
- [ ] Confirm per-plan seat/concurrency numbers and whether keys are device-bound (server/binary-side,
  not in this repo).

This is the one item that blocks **revenue**, not development — milestone 1 (a signed local app that
auto-downloads the engine per user) can be built and tested while this is resolved.
