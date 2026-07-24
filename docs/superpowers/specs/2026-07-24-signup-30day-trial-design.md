# Sign-up + 30-day Trial — Design

**Date:** 2026-07-24
**Status:** Approved (design); implementation pending

## Goal

Add an in-app **Sign up** flow to the desktop Plasma app: a panel in the License
screen with **email + password + confirm-password** that creates a cloud account and
grants a **30-day trial license**, activated on the device — in one submit, no email
verification. When the 30 days elapse, the license hard-expires and the app locks
(reusing existing expired-license enforcement).

## Decisions (locked during brainstorming)

1. **In-app cloud sign-up** — a `SignUpPanel` in the desktop `LicenseScreen` (alongside
   the existing Sign in / Activate), backed by the cloud control plane. Not a hosted web
   page, not a local-only key.
2. **30-day trial that hard-expires** — access is granted immediately and hard-stops
   exactly 30 days after sign-up; the license goes `expired` and the app locks.
3. **Instant, no email verification** — the account is created `active`; the trial is
   granted and the user signed in in one step.

## Non-goals

- No email-verification UI or real email provider wiring (accounts are created active;
  verification can be added later for paid conversion).
- No payment / paid-plan purchase flow (post-trial, the user Activates a real key via the
  existing Activate panel).
- No change to the **local owner** setup (`manager_backend/auth/routes.py` `/auth/setup`)
  — that gates the app UI and is unrelated to the cloud account/license.
- Three-ports rule (Python/JS/.NET) does **not** apply — this is `cloud/` +
  `manager_backend/` + `manager/frontend/`, not the `cloakbrowser` wrapper.

## Flow

```
SignUpPanel (email, password, confirm)
  → api.accountRegister({ email, password })            [confirm is client-side only]
  → manager_backend  POST /api/v1/account/register
  → AccountService.register(email, password)
      → CloudClient.register(email, password, device_proof)
        → cloud  POST /auth/signup   (ATOMIC):
            1. create User (status=active — skip verification)
            2. ensure "trial" Plan exists (seeded by migration)
            3. issue trial ActivationKey (plan=trial, max_uses=1, expires_at = now+30d)
            4. attach this device (Ed25519 possession proof) + mint refresh session
            5. redeem the key for this device → sign entitlement (with trial_end claim)
            6. return { session, entitlement }
      → store session (like login) + license_service.install_entitlement(entitlement)
  → license.allowed = true  → LicenseGate unlocks the app
```

One cloud round-trip; the trial key is never exposed to the client.

## The 30-day mechanism (precise + architecture-consistent)

Three coordinated pieces so the boundary lands at exactly 30 days without breaking the
existing 24h-entitlement + refresh + revocation model:

1. **Trial key `expires_at = signup + 30d`** (`cloud/admin.issue_key` already supports
   this) → stops entitlement **re-issuance** at day 30 via the existing `key_expired`
   path (`cloud/licensing.py`).
2. **New `trial_end` claim** in the signed entitlement = `signup + 30d`
   (`cloud/entitlements.py` / `cloud/licensing.py:redeem_key`).
3. **Desktop state-machine hard cap:** `manager_backend/features/license/service.py`
   adds one rule — if `now > trial_end` (from the verified entitlement claim), state is
   `expired`, independent of the 24h `exp` / 7d offline-grace. Within the 30 days, the
   normal 24h refresh (`refresh_entitlement`) keeps working so revocation still functions.

This reuses the existing `expired` state and its enforcement (launch gate in
`RuntimeManager.start`); no new lock mechanism.

## Components

### Cloud (`cloud/`)
- **`POST /auth/signup`** (`cloud/features/auth/routes.py` + `service.py`) — bundles
  register-active + issue-trial-key + device-attach + session + redeem, returning
  `{ session, entitlement }`. Reuses `register_user`, `issue_key`, `redeem_key`, the
  device-attach/session logic from `/auth/token`, and entitlement signing.
- **Active-on-create path** — `register_user(...)` gains a way to create the user
  `status="active"` for the trial (parameter or a sibling `create_trial_user`), skipping
  the `EmailVerification` step.
- **Trial Plan seed** — a new migration under `cloud/migrations/versions/` inserts a
  `trial` `Plan` row (e.g. `max_devices=1`, minimal claims) so the trial key has a
  `plan_id` to reference. Idempotent seed.
- **`trial_end` claim** — added to the entitlement claims when redeeming a trial key,
  set to the trial key's `expires_at` (the single source of truth for the 30-day
  boundary; `refresh_entitlement` re-mints carry the same `trial_end`).
- **Schemas** (`cloud/schemas.py`) — `SignupRequest { email, password, device }`
  (password `min_length=12`, matching `RegisterRequest`); `SignupResponse { session,
  entitlement }`.
- **Trial guard** — one active trial per email (duplicate email → `email_taken`, the
  existing error); optionally block a second trial for the same account (out of scope to
  fully prevent multi-account abuse — noted below).

### Desktop backend (`manager_backend/features/account/`)
- **`CloudClient.register(email, password, device)`** (`cloud_client.py`) — POSTs
  `/auth/signup`; mirrors the existing `login()` httpx pattern.
- **`AccountService.register(email, password)`** (`service.py`) — calls
  `CloudClient.register`, stores the returned session (as `login()` does), and
  `license_service.install_entitlement(entitlement)` (as `activate()` does). One method =
  register + login + activate.
- **`POST /api/v1/account/register`** (`routes.py`) + **`RegisterRequest`**
  (`schemas.py`) `{ email, password }` (confirm is client-side only).
- **License state machine** (`features/license/service.py`) — the `trial_end` hard-cap
  rule above; `verifier.py` exposes the `trial_end` claim.

### Frontend (`manager/frontend/src/`)
- **`SignUpPanel`** in `features/account/LicenseScreen.tsx` — email + password + confirm;
  confirm validated client-side with the existing `AuthGate.tsx` pattern
  (`validate: value === watch('password')`); submit → `useAccountRegister`.
- **`useAccountRegister`** hook (`features/account/api.ts`) — mutation → `api.accountRegister`,
  on success invalidates `license` + `account` queries so `LicenseGate` re-evaluates.
- **Adapter surface** — `accountRegister(payload)` on `ApiAdapter` (`api/adapter.ts`),
  `realApi` (`api/real.ts` → `POST /account/register`), and `mockApi` (`mocks/mockApi.ts`
  → returns an active trial license fixture).
- **Type** — `AccountRegisterRequest { email: string; password: string }` in
  `types/api.ts`.
- **Panel toggle** — `LicenseScreen` shows a link to switch Sign in ⇄ Sign up (e.g.
  "Start a 30-day free trial"); i18n en + vi strings.

## Error handling

- `email_taken` (duplicate) → inline "an account with this email already exists" on the
  sign-up form (reuses the cloud error).
- Password too short (`min_length=12`) → client-side + server 422.
- Confirm mismatch → client-side only, never submitted.
- Cloud unreachable / signup failed → the existing account error surface ("couldn't reach
  the licensing service"); no partial local state is stored (install entitlement only on
  a fully-successful signup response).
- Device cap / redeem failure → surfaced as an activation error; the account still exists
  (user can Sign in later).
- Fixed error codes only; never log the password or the trial key.

## Security

- Password: argon2id server-side (`cloud/passwords.py`); never stored/logged in plaintext;
  email normalized + uniqueness enforced (`cloud/keys.normalize_email`).
- The trial entitlement is Ed25519-signed (`PLASMA_SIGNING_PRIVATE_KEY_PEM`) and verified
  offline on the desktop (`PLASMA_ENTITLEMENT_PUBKEY`) — unchanged trust chain.
- The trial key never leaves the cloud (redeemed server-side in the same call).
- **Abuse (accepted for now):** one trial per email, but nothing stops many free-email
  accounts. Acceptable for a trial; a future anti-abuse pass (email verification, device
  fingerprint, rate limit) can tighten it — noted, not built.
- `confirm_password` is a client-only UX check (matches the existing pattern); the server
  never receives it.

## Testing (TDD)

- **Cloud:** `POST /auth/signup` creates an `active` user, issues a key with
  `expires_at == signup+30d`, returns a session + a verifiable entitlement whose
  `trial_end == signup+30d`; duplicate email → `email_taken`; short password → 422; the
  trial Plan seed migration is present and idempotent.
- **Desktop backend:** `AccountService.register` orchestration with a **fake CloudClient**
  (stores session + installs entitlement on success; stores nothing on failure); the
  `/account/register` route (happy path + error passthrough); the license state-machine
  `trial_end` hard-cap (`active` at `trial_end - 1s`, `expired` at `trial_end + 1s`).
- **Frontend:** `SignUpPanel` against the mock — confirm-mismatch blocks submit;
  successful register flips the license gate to unlocked; duplicate-email error renders.

## Enforcement & test environment

License enforcement is **off by default** (`PLASMA_REQUIRE_LICENSE`), so `LicenseGate`
passes through without a license in the normal dev/free build. To exercise sign-up
end-to-end: run the desktop with `PLASMA_REQUIRE_LICENSE=1` and `PLASMA_CLOUD_URL` pointed
at a **locally-run `cloud/`** (with `PLASMA_SIGNING_PRIVATE_KEY_PEM` / matching
`PLASMA_ENTITLEMENT_PUBKEY` and `PLASMA_ACTIVATION_PEPPER` set). The feature builds the
capability; production still requires the cloud deployed (a known pre-launch item).

## Future (not in this spec)

- Email verification + real email provider (currently `ConsoleEmailSender`).
- Paid-plan purchase / trial→paid conversion.
- Anti-abuse (rate limits, one-trial-per-device).
