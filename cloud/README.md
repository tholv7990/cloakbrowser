# Plasma cloud control plane

Accounts, sessions, devices, activation keys, entitlements, and update metadata for
Plasma. **Never runs a browser or stores browser data.** FastAPI + PostgreSQL,
modular monolith, deployed with Docker Compose behind Caddy (auto-TLS). Sized for a
small VPS (2–4 vCPU / 4–8 GB). Design: `../docs/architecture/plasma-desktop-cloud/`.

## Layout

```
cloud/
  app.py            FastAPI create_app() (uvicorn --factory cloud.app:create_app)
  config.py         CloudSettings (secrets from env; generate_test_settings for tests)
  db.py models.py   SQLAlchemy 2.0 schema (Postgres prod / SQLite tests)
  migrations/       Alembic (alembic -c cloud/alembic.ini upgrade head)
  keys.py           activation-key gen + HMAC verifier (no plaintext keys)
  entitlements.py   EdDSA-signed entitlement + verify
  tokens.py         refresh (hashed) + short access JWS
  passwords.py      argon2id
  licensing.py      race-safe redeem + entitlement refresh
  email.py          injectable sender (console/prod, recording/tests)
  features/{auth,devices,activation}/  service + routes
  Dockerfile docker-compose.yml Caddyfile requirements.txt
```

## Secrets (environment — never commit)

| Var | What |
|---|---|
| `PLASMA_CLOUD_DATABASE_URL` | PostgreSQL DSN, e.g. `postgresql+psycopg://plasma:…@postgres:5432/plasma` |
| `PLASMA_ACTIVATION_PEPPER` | base64 of ≥32 random bytes — HMAC pepper for activation-key verifiers |
| `PLASMA_SIGNING_PRIVATE_KEY_PEM` | Ed25519 private key (PEM). Its **public** half is pinned in the desktop app. |
| `POSTGRES_PASSWORD`, `CLOUD_DOMAIN` | compose only |

Generate the signing key + pepper:

```bash
# Ed25519 signing key (PEM) -> PLASMA_SIGNING_PRIVATE_KEY_PEM
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization as s; k=Ed25519PrivateKey.generate(); print(k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode())"
# The pinned public key (base64) for the desktop:
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64,os; # load your key and print base64(raw pub)"
# Activation pepper:
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

## Run

```bash
# from the repo root; put the vars above in cloud/.env (gitignored)
docker compose -f cloud/docker-compose.yml --env-file cloud/.env up -d --build
# migrations run automatically on app start (alembic upgrade head)
```

## Tests

```bash
python -m pytest tests/cloud -q      # 53 tests: schema, licensing, auth, devices, API
```

## Endpoints (v1)

`POST /auth/register` · `POST /auth/verify-email` · `POST /auth/token` (login + device
attach) · `POST /auth/token/refresh` · `POST /auth/logout` · `POST /auth/logout-all` ·
`GET /devices` · `POST /devices/{id}/revoke` · `POST /activation/redeem` ·
`POST /entitlement/refresh` · `GET /health`.

## Not yet wired (next)

PKCE `/authorize`+`/token` hosted browser flow, password-reset routes, per-scope
rate-limit/lockout enforcement (tables exist: `auth_throttle`), admin CLI (issue/
revoke keys, support lookup by prefix), update-release endpoints, Sentry. See the
repo backlog.
