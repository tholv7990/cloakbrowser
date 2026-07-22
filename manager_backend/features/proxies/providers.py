"""Residential proxy providers (IPRoyal, 711Proxy).

Connect a provider account, then generate residential proxies straight into the
proxy pool. Credentials live in the secure CredentialStore only — never the DB,
never a response. `configured` is derived from the store, so there is no
provider table.

711Proxy credential mode builds sticky-session routes locally (no HTTP), so it
is fully testable. IPRoyal needs the live API, so it sits behind an injectable
client (`app.state.proxy_provider_client`) that tests replace with a fake.
Reference: Quantum `backend/services/{iproyal,seveneleven_proxy}_service.py`.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import Proxy
from .credentials import CredentialStore, ProxyCredential


# Provider identity ----------------------------------------------------------
PROVIDER_IDS = ("iproyal", "seveneleven")
PROVIDER_NAMES = {"iproyal": "IPRoyal", "seveneleven": "711Proxy"}
_IPROYAL_TOKEN_USER = "iproyal-token"  # username slot when storing a bare token
_ELEVEN_HOST = "global.711proxy.com"
_ELEVEN_PORT = 20000
_GENERATED_SCHEME = "socks5h"


def _store_ref(provider: str) -> str:
    return f"proxy-provider:{provider}"


def _country_code(country: str) -> str:
    code = str(country or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{2}", code) else ""


@dataclass(frozen=True, slots=True)
class GeneratedProxy:
    host: str
    port: int
    username: str
    password: str


# 711Proxy — local sticky-session construction (no network) ------------------
def _sticky_minutes(session_type: str) -> int:
    # 711 clamps sessTime to 5–180. Sticky holds an IP for the window; rotating
    # uses the shortest window so the exit rotates quickly.
    return 30 if session_type == "sticky" else 5


def build_seveneleven_routes(
    credential: ProxyCredential, count: int, country: str, session_type: str
) -> list[GeneratedProxy]:
    """Build `count` distinct 711Proxy sticky routes from sub-user credentials.

    Each route encodes region + a unique session in the username directive, so
    the gateway (`global.711proxy.com:20000`) returns a distinct exit per proxy.
    """
    base = str(credential.username or "").strip()
    password = str(credential.password or "").strip()
    if not base or not password:
        raise ManagerError(
            "proxy_provider_not_configured", "Connect 711Proxy credentials first.", 422
        )
    code = _country_code(country)
    minutes = _sticky_minutes(session_type)
    routes: list[GeneratedProxy] = []
    for _ in range(count):
        parts = [base]
        if code:
            parts += ["region", code]
        parts += ["session", f"{secrets.randbelow(100_000_000):08d}", "sessTime", str(minutes)]
        routes.append(
            GeneratedProxy(_ELEVEN_HOST, _ELEVEN_PORT, "-".join(parts), password)
        )
    return routes


# IPRoyal — live API ---------------------------------------------------------
def _fresh_session_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class ProviderClient(Protocol):
    def generate(
        self, provider: str, credential: ProxyCredential, count: int, country: str, session_type: str
    ) -> list[GeneratedProxy]: ...


class IPRoyalApi:
    """Thin IPRoyal residential API client (urllib). Ported from Quantum."""

    API_ROOT = "https://resi-api.iproyal.com/v1"

    def _request(self, path: str, token: str, method: str = "GET", payload: dict | None = None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.API_ROOT}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ManagerError(
                    "proxy_provider_rejected",
                    "IPRoyal rejected this API token. Reconnect the provider.",
                    422,
                ) from exc
            raise ManagerError(
                "proxy_provider_error", f"IPRoyal API returned HTTP {exc.code}.", 502
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc)
            raise ManagerError(
                "proxy_provider_unreachable", f"Could not reach IPRoyal: {reason}", 502
            ) from exc
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            raise ManagerError(
                "proxy_provider_error", "IPRoyal returned an invalid response.", 502
            ) from exc

    def _first_funded_subuser(self, token: str) -> str:
        payload = self._request("/residential-subusers?page=1&per_page=100", token)
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        for item in rows if isinstance(rows, list) else []:
            if isinstance(item, dict) and float(item.get("traffic_available") or 0) > 0:
                subuser_hash = str(item.get("hash") or "").strip()
                if subuser_hash:
                    return subuser_hash
        raise ManagerError(
            "proxy_provider_no_capacity",
            "No IPRoyal sub-user has traffic. Allocate traffic to a sub-user in IPRoyal first.",
            422,
        )

    def generate(
        self, provider: str, credential: ProxyCredential, count: int, country: str, session_type: str
    ) -> list[GeneratedProxy]:
        token = str(credential.password or "").strip()  # token stored in the password slot
        if not token:
            raise ManagerError(
                "proxy_provider_not_configured", "Connect an IPRoyal API token first.", 422
            )
        rotation = "sticky" if session_type == "sticky" else "random"
        code = _country_code(country)
        request_payload = {
            "format": "{hostname}:{port}:{username}:{password}",
            "hostname": "geo.iproyal.com",
            "port": "socks5",
            "rotation": rotation,
            "location": f"_country-{code.lower()}" if code else "",
            "proxy_count": count,
            "subuser_hash": self._first_funded_subuser(token),
        }
        if rotation == "sticky":
            request_payload["lifetime"] = "24h"
        raw = self._request("/access/generate-proxy-list", token, "POST", request_payload)
        source = raw.get("data") or raw.get("proxies") if isinstance(raw, dict) else raw
        lines = [str(x).strip() for x in source] if isinstance(source, list) else []
        lines = [line for line in lines if line]
        if not lines:
            raise ManagerError(
                "proxy_provider_error", "IPRoyal returned an empty proxy list.", 502
            )
        return [self._to_proxy(line, rotation) for line in lines]

    @staticmethod
    def _to_proxy(line: str, rotation: str) -> GeneratedProxy:
        parts = line.split(":", 3)
        if len(parts) != 4 or not parts[1].isdigit():
            raise ManagerError(
                "proxy_provider_error", "IPRoyal returned a proxy in an unsupported format.", 502
            )
        host, port, username, password = parts
        if rotation == "sticky":
            # Replace the sticky session so parallel single generations never
            # collide on the same route.
            password = re.sub(r"_session-[^_:\s]+", "", password, flags=re.IGNORECASE)
            password = f"{password}_session-{_fresh_session_id()}_lifetime-24h"
        return GeneratedProxy(host, int(port), username, password)


class DefaultProviderClient:
    """Dispatches to the right provider. Injected as app.state.proxy_provider_client."""

    def __init__(self, iproyal: IPRoyalApi | None = None):
        self._iproyal = iproyal or IPRoyalApi()

    def generate(
        self, provider: str, credential: ProxyCredential, count: int, country: str, session_type: str
    ) -> list[GeneratedProxy]:
        if provider == "seveneleven":
            return build_seveneleven_routes(credential, count, country, session_type)
        if provider == "iproyal":
            return self._iproyal.generate(provider, credential, count, country, session_type)
        raise ManagerError("proxy_provider_unknown", "Unknown proxy provider.", 422)


# Service ---------------------------------------------------------------------
def list_providers(store: CredentialStore) -> list[dict]:
    return [
        {
            "id": provider,
            "name": PROVIDER_NAMES[provider],
            "configured": store.get(_store_ref(provider)) is not None,
        }
        for provider in PROVIDER_IDS
    ]


def save_provider_credentials(store: CredentialStore, provider: str, *, api_token, username, password) -> dict:
    if provider == "iproyal":
        token = str(api_token or "").strip()
        if not token:
            raise ManagerError("proxy_provider_invalid", "An IPRoyal API token is required.", 422)
        store.put(_store_ref(provider), ProxyCredential(_IPROYAL_TOKEN_USER, token))
    else:  # seveneleven
        user = str(username or "").strip()
        secret = str(password or "").strip()
        if not user or not secret:
            raise ManagerError(
                "proxy_provider_invalid", "A 711Proxy username and password are required.", 422
            )
        store.put(_store_ref(provider), ProxyCredential(user, secret))
    return {"id": provider, "name": PROVIDER_NAMES[provider], "configured": True}


def _unique_label(name: str, code: str, session_type: str, taken: set[str]) -> str:
    prefix = f"{name} {code or 'GLOBAL'} {session_type.title()}"
    while True:
        label = f"{prefix} {secrets.token_hex(3).upper()}"
        if label.casefold() not in taken:
            taken.add(label.casefold())
            return label


def generate_and_store(
    session: Session,
    store: CredentialStore,
    client: ProviderClient,
    *,
    provider: str,
    count: int,
    country: str,
    session_type: str,
) -> dict:
    """Generate `count` residential proxies and insert them into the pool."""
    credential = store.get(_store_ref(provider))
    if credential is None:
        raise ManagerError(
            "proxy_provider_not_configured",
            f"Connect {PROVIDER_NAMES.get(provider, provider)} first.",
            422,
        )
    generated = client.generate(provider, credential, count, country, session_type)
    name = PROVIDER_NAMES[provider]
    code = _country_code(country)
    taken = {
        label.casefold()
        for label in session.scalars(select(Proxy.label).where(Proxy.deleted_at.is_(None)))
    }
    refs: list[str] = []
    proxies: list[Proxy] = []
    for gp in generated:
        ref = str(uuid4())
        store.put(ref, ProxyCredential(gp.username, gp.password))
        refs.append(ref)
        proxy = Proxy(
            label=_unique_label(name, code, session_type, taken),
            scheme=_GENERATED_SCHEME,
            host=gp.host,
            port=gp.port,
            credential_ref=ref,
            proxy_type="residential",
            organization=name,
            country=code or None,
            test_before_launch=True,
        )
        session.add(proxy)
        proxies.append(proxy)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        for ref in refs:
            store.delete(ref)
        raise ManagerError(
            "proxy_provider_conflict",
            "Generated proxies collided with existing ones. Try again.",
            409,
        ) from None
    for proxy in proxies:
        session.refresh(proxy)
    return {"created": len(proxies), "proxy_ids": [proxy.id for proxy in proxies]}
