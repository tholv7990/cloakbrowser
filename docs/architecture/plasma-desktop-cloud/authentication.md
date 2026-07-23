# Authentication

**Status:** design. How a Plasma desktop install proves who the user is to the cloud, keeps a session
securely across launches, and revokes access cleanly. No permanent secret is embedded in the app.

## Flow choice (evaluated)

| Option | Verdict |
|---|---|
| **OAuth 2.1 Authorization Code + PKCE via the system browser** (RFC 8252) | **Recommended v1.** The app never sees the password; MFA/passkeys/SSO plug in later without a client change; standard, hard to get wrong. |
| Embedded email/password login (app POSTs credentials) | Simpler, but the desktop handles the password, and MFA/passkeys become awkward. **Acceptable fallback** only if hosting a login page is too much for the very first cut — documented as a downgrade. |
| Device Authorization Grant (enter a code) | Nice for headless/TV; unnecessary friction on a desktop with a browser. **Postpone.** |
| Passkeys (WebAuthn) | **Roadmap** — add as an MFA/passwordless option on the hosted login page once accounts exist; no desktop change needed. |

**Recommendation:** system-browser Authorization Code + PKCE, loopback redirect. The desktop opens the
OS browser to the cloud's hosted `/authorize`; the user authenticates there (password, later
MFA/passkey); the browser redirects to `http://127.0.0.1:<random>/callback` that the desktop is
listening on; the desktop exchanges the code (+ PKCE verifier) for tokens.

## Registration

1. Desktop opens system browser → hosted sign-up. Server creates `users` row (email +
   **argon2id** hash — same family as the local `auth/passwords.py:8-15`), status `unverified`.
2. Server emails a single-use, expiring verification link. Clicking it marks the account `active`.
3. No tokens are issued to an `unverified` account.

## Login (Authorization Code + PKCE)

```mermaid
sequenceDiagram
  participant App as Desktop app
  participant Br as System browser
  participant AS as Cloud auth server
  App->>App: generate code_verifier; code_challenge=S256(verifier); state; nonce
  App->>App: start loopback listener 127.0.0.1:R
  App->>Br: open /authorize?response_type=code&code_challenge&state&nonce&redirect_uri=127.0.0.1:R
  Br->>AS: user authenticates (password, later MFA/passkey)
  AS->>Br: 302 redirect_uri?code=...&state=...
  Br->>App: GET /callback?code&state
  App->>App: verify state matches
  App->>AS: POST /token (code, code_verifier, device_pubkey)
  AS->>AS: verify PKCE + bind session to device key
  AS-->>App: access JWT (short) + refresh (rotating, device-bound) + id/nonce check
  App->>App: store refresh + device key in DPAPI/Credential Manager (never SQLite plaintext)
```

Requirements enforced: **PKCE S256** (no plain); **state** (CSRF for the redirect); **nonce** (id
token replay); exact loopback `redirect_uri`; **TLS validated normally** (no cert-error bypass);
tokens **never** in a URL we log or persist in plaintext.

**Implemented (concrete endpoints).** The desktop opens `GET /oauth/login?redirect_uri&code_challenge&state`.
That page (`cloud/features/oauth/login_page.py`) is fully static — it reads those params
client-side (nothing is reflected into the HTML, so no XSS) and POSTs credentials to
`POST /oauth/authorize`, which authenticates, mints a single-use code, and returns it; the
page then redirects to `redirect_uri?code&state`. The desktop exchanges at `POST /oauth/token`.
`/oauth/authorize` **rejects any non-loopback `redirect_uri`** (`is_loopback_redirect_uri`,
RFC 8252: `http` on `127.0.0.1` / `localhost` / `[::1]`) → `invalid_request`, so a hostile
redirect can't exfiltrate a victim's code. The page ships a strict CSP (`default-src 'none'`,
inline style/script only, `connect-src 'self'`).

## Token lifecycle

- **Access token:** EdDSA-signed JWT, **short (~10 min)**. Sent as `Authorization: Bearer` to cloud
  APIs. Stateless-verified via the cloud's public key.
- **Refresh token:** opaque, **rotated on every use**; each session is a *family*; presenting an old
  (already-rotated) refresh triggers **reuse detection → revoke the whole family** (stolen-token
  containment). Refresh is **device-bound**: the refresh call is signed by the device private key
  (see [device-identity.md](device-identity.md)), so a refresh token exfiltrated without the device
  key is useless.
- **Storage:** refresh token + device private key live in **Windows DPAPI / Credential Manager** —
  never in SQLite, never in logs, never in a URL.

```mermaid
sequenceDiagram
  participant App
  participant AS as Cloud
  App->>AS: POST /token/refresh (old_refresh, device-signed challenge)
  AS->>AS: valid + not reused? rotate; else revoke family
  AS-->>App: new access + new refresh
  App->>App: overwrite stored refresh (DPAPI)
```

## Password recovery

1. User requests reset (hosted page) → server emails a single-use, short-TTL, rate-limited link.
2. Setting a new password: re-hash (argon2id) and **revoke all existing sessions/refresh families**
   for that user (below). A generic response either way avoids account enumeration (mirrors the
   local `invalid_credentials` discipline, `auth/routes.py:105`).

## Logout & revocation

- **Logout (this device):** revoke the current refresh family; discard local tokens. Local profiles
  untouched.
- **Log out all devices:** revoke every refresh family for the user.
- **Password change:** revoke appropriate sessions (all, or all-but-current per policy).
- **Device revocation:** the device's refresh family is revoked **and** its `devices` row marked
  revoked → entitlement refresh for that device fails (see activation doc). Local data is not deleted;
  launches lock at grace expiry.
- Access tokens are short, so revocation propagates within the access-token lifetime online; offline,
  the entitlement grace window bounds it.

## MFA roadmap (postpone for v1)

TOTP first (hosted enrollment), then WebAuthn/passkeys — both live on the hosted login page, so the
desktop PKCE flow needs **no change** to gain them. Recovery codes issued at enrollment.

## Rate limiting & abuse

Per-IP + per-account limits with backoff/lockout on login, token, reset, and (see activation)
redemption. This replaces the local single-global-counter throttle (`auth/routes.py:99-105`), which is
fine for a loopback owner login but inadequate for an internet-facing service.

## Non-negotiables (checklist)

- [ ] No permanent API key in the desktop binary.
- [ ] Access short-lived; refresh rotated + device-bound; reuse → family revoke.
- [ ] Refresh + device key in DPAPI/Credential Manager; never SQLite/logs/URLs.
- [ ] TLS validated; no cert-error bypass.
- [ ] PKCE S256 + state + nonce on the browser flow.
- [ ] Logout / logout-all / password-change / device-revoke all revoke correctly.
