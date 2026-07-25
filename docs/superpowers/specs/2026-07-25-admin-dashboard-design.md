# Super-admin dashboard — users & licensing

**Goal:** a web dashboard for the super admin to manage customers, licences, seats
and releases, replacing today's CLI-only administration.

## What already exists (don't rebuild it)

- `cloud/admin.py` — **CLI only**, no HTTP routes, no UI. Already implements
  `issue_key`, `set_key_status`, `set_user_status`, `lookup_key`.
- `User.role` with `CHECK role in ('user','admin')` — the admin role exists.
- Models covering the whole domain: `User`, `Device`, `Session`, `Plan`,
  `ActivationKey`, `Redemption`, `Entitlement`, `Subscription`, `AuditEvent`,
  `UpdateRelease`, `EmailVerification`, `PasswordReset`.

So the work is: **expose the existing operations as authenticated HTTP endpoints,
add the ones support actually needs, and build a UI.** The schema is largely there.

## Where it lives

A **separate web app served by the cloud control plane**, not the desktop app. The
super admin manages every customer; the desktop app is one customer's machine and
must never carry admin capability. Keeping them separate means no admin code ships
in the product binary.

## Functionality

### Users
- Search/list by email, plan, status, signup date; paginated.
- Detail view: plan, subscription, devices, active sessions, keys, redemptions.
- Suspend / reactivate (exists: `set_user_status`).
- Force email verification, trigger password reset.
- Delete / anonymise (GDPR request path).

### Licences & keys
- Issue single or **bulk** keys against a plan, with expiry (exists: `issue_key`).
- Look up a key and see who redeemed it, when, on which device (`lookup_key`,
  `Redemption`).
- Revoke / suspend / reactivate (exists: `set_key_status`).
- Extend expiry — the common support request; currently impossible without SQL.

### Seats & devices — the highest-value support tool
- List a user's devices and which hold seats.
- **Release a seat / de-authorise a device.** "I reinstalled Windows and can't
  activate" is the single most common licensing ticket, and today it needs manual
  DB work. This alone justifies the dashboard.
- Show seat usage against the plan limit (`Plan` seat limits, exit code 76 path).

### Plans & subscriptions
- List plans, seat limits, trial plan (`TRIAL_PLAN_ID`, 30-day).
- Per-user: subscription status, renewal/expiry, cancel.

### Entitlements
- View a user's current entitlement and its TTL; force refresh; revoke.

### Releases
- List/publish `UpdateRelease` rows — which binary version each tier resolves to.
  Pairs with the free-vs-Pro version resolution in the wrapper.

### Analytics (start small)
- Active users, activations in period, seats in use vs sold, keys expiring in 30
  days, trials converting. Resist a BI project — these five answer most questions.

### Audit
- Read-only view of `AuditEvent`. **Every admin mutation must write one** with
  actor, target, before/after. Non-negotiable: admin actions change what customers
  paid for.

## Security requirements

1. **Role gate on every endpoint** — `role == 'admin'`, checked server-side per
   request, never inferred from the UI.
2. **Separate session scope** from customer sessions; short idle timeout.
3. **Audit everything**, including reads of key material.
4. **No secret echo** — never return a full activation key or password hash in a
   list response; reveal on explicit single-record request only, and audit it.
5. **Rate-limit + throttle** admin auth (`AuthThrottle` exists).
6. Consider an **IP allowlist** for the admin surface; it is a total-compromise
   target — anyone in it can mint licences.

## Suggested phasing

1. **Admin API + auth gate** — expose the four existing CLI operations over HTTP,
   role-gated and audited. No UI yet; verifiable with tests.
2. **Users + keys UI** — list, search, detail, suspend, issue, revoke.
3. **Seats/devices** — release a seat. Highest support value.
4. **Plans, subscriptions, entitlements.**
5. **Analytics + audit log view.**
6. **Releases.**

Phase 1 is the real unlock: once the API exists and is audited, the UI is
incremental and each phase ships independently.

## Open questions for the product owner

- One super admin, or multiple staff with roles (support vs billing vs owner)? The
  `role` CHECK currently allows only `user`/`admin`; more roles means a migration.
- Should support staff be able to *impersonate* a customer to debug? Powerful and
  a common source of incidents — if yes, it must be audited and time-boxed.
- Refunds/billing: in scope, or handled in the payment provider's own dashboard?
