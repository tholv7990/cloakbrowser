# Persistent Local Owner Session Design

## Decision

CloakBrowser Manager keeps the local owner's authenticated session until the owner explicitly revokes it. There is no inactivity timeout and no absolute time limit.

The session remains valid across dashboard refreshes, app restarts, browser restarts, and Windows restarts. This matches the product's single-user, local-only purpose and avoids repeatedly asking the owner to log in on their own computer.

## Revocation

A session ends only when one of these events occurs:

- The owner logs out, which revokes the current session.
- The owner locks the manager, which revokes every session.
- The owner changes the password, which revokes every session.
- The authentication database or app data is removed.

Closing the dashboard, manager process, or Windows does not revoke a session.

## Storage and Cookie Behavior

The opaque session token remains in an `HttpOnly`, `SameSite=Strict` cookie. The cookie is persistent and has no application-level expiry date. SQLite stores only the SHA-256 token hash, never the token itself.

The CSRF token remains in a separate `SameSite=Strict` cookie and must be copied into `X-CSRF-Token` for mutations. Exact configured Origin validation remains required. HTTPS configurations continue setting `Secure` on both cookies.

The authentication session record no longer needs `last_seen_at` or `absolute_expires_at`. A migration removes those columns. Existing unrevoked sessions survive the migration and become persistent; revoked sessions remain revoked.

## API Contract

Setup and login continue returning the owner email and CSRF token. Session responses no longer return `idle_expires_at` or `absolute_expires_at`, because neither value exists. No password, password hash, or opaque session token appears in an API response.

The frontend treats HTTP 401 as revoked or invalid authentication, not time expiration. It directs the owner to the login screen in that case.

## Error Handling

Missing, unknown, or revoked session cookies produce the existing safe `authentication_required` response. The `session_expired` error is removed. Origin and CSRF failures retain their current safe error codes.

## Verification

Tests prove that a session remains valid even when its creation and last-use timestamps are far in the past. Separate tests continue proving logout, lock, and password change revocation. Migration tests verify that an existing unrevoked session remains usable and that the schema has no expiry columns.

The exported OpenAPI document must show the reduced session response and must continue declaring cookie and CSRF security schemes.
