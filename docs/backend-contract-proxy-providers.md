# Backend contract — Proxy providers (`/proxies/providers`)

**Owner:** backend (Codex). Frontend is built (a "Providers" dialog on the Proxies screen, `features/proxies/ProvidersDialog.tsx`, EN/VI).

**Reference:** `Quantum-Source-Clean-*/backend/services/{iproyal_service,seveneleven_proxy_service}.py`, `backend/services/profile_factory_service.py` (which consumes generated proxies).

## Goal

Connect **IPRoyal** and **711Proxy** accounts, then **generate residential proxies** directly into the existing proxy pool. Provider credentials are stored securely and never returned.

## Endpoints (under the existing proxies router, prefix `/api/v1/proxies`)

```
GET  /proxies/providers              -> 200 ProxyProvider[]
PUT  /proxies/providers/{provider}   -> 200 ProxyProvider     # save credentials
POST /proxies/providers/generate     -> 200 GenerateProxiesResult
```

`{provider}` ∈ `iproyal | seveneleven`. Same session/origin auth as other routes.

## Response / request shapes

Mirror the TS types in `manager/frontend/src/types/api.ts`:

```jsonc
// ProxyProvider (GET list) — NO secrets
{ "id": "iproyal", "name": "IPRoyal", "configured": true }

// PUT /proxies/providers/{provider} body (ProxyProviderConfigPayload)
{ "provider": "iproyal", "api_token": "..." }                 // IPRoyal
{ "provider": "seveneleven", "username": "...", "password": "..." }  // 711Proxy
// → returns the ProxyProvider with configured=true (secrets never echoed)

// POST /proxies/providers/generate body (GenerateProxiesPayload)
{ "provider": "iproyal", "count": 5, "country": "US", "session_type": "rotating" }  // 'rotating' | 'sticky'
// → GenerateProxiesResult
{ "created": 5, "proxy_ids": ["px_...", "px_..."] }
```

## Data model + secrets

- Provider config lives per provider: a `proxy_provider` table (or a small settings row) holding `id`, `configured`, and a `credentials_ref` → the **secure credential store** (`features/proxies/credentials.py` `CredentialStore`). **Never** store the token/username/password in the DB, and **never** return them.
- `configured` is derived: true once a credentials ref exists.

## Implementation

- **Save credentials** (`PUT`): validate the shape per provider (IPRoyal needs `api_token`; 711 needs `username`+`password`), store the secret in `CredentialStore` keyed by provider, set `configured=true`. Optionally verify the credentials against the provider API and 422 on failure.
- **Generate** (`POST`): require the provider `configured` (422 otherwise). Call the provider API to allocate `count` residential endpoints for `country`/`session_type`:
  - IPRoyal: token connect → generate residential proxies (see `iproyal_service.py` — location tree, subuser/session handling).
  - 711Proxy: api-url or credentials → sticky/rotating generation (`seveneleven_proxy_service.py`).
  Then **insert each into the proxy pool** as a normal `Proxy` row (scheme `socks5h`, host/port/username from the provider, password to the secure store, `proxy_type='residential'`, `organization=<provider name>`, `country`), and return `{ created, proxy_ids }`. Clamp `count` (1–50). The generated proxies then behave like any hand-added proxy (assignable, testable).

## Security

- Credentials → secure store only, never DB, never in any API payload. `GET /proxies/providers` exposes `configured` only. Generated proxy passwords follow the same rule as manual proxies (secure store; responses carry `has_password`/`masked_endpoint` only).

## Tests

`tests/manager/test_proxy_providers_api.py` (mock the provider HTTP): `GET /providers` never leaks secrets; `PUT` with valid creds flips `configured` true and stores to the credential store (not the DB); `POST /generate` is 422 when unconfigured, and when configured inserts `count` residential `Proxy` rows into the pool and returns their ids. Update `openapi.json` if checked in.
