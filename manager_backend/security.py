from __future__ import annotations

import re
import secrets

from fastapi import Request

from .errors import ManagerError


_PROXY_CREDENTIALS = re.compile(
    r"(?P<scheme>https?|socks5h?)://[^\s/@:]+:[^\s/@]+@",
    flags=re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"\bBearer\s+[^\s,;]+", flags=re.IGNORECASE)


def redact_text(value: str) -> str:
    value = _PROXY_CREDENTIALS.sub(r"\g<scheme>://***:***@", value)
    return _BEARER_TOKEN.sub("Bearer ***", value)


async def require_local_token(request: Request) -> None:
    """Require a valid per-install/per-process local Bearer token, when enabled.

    Off by default (dev/browser workflow). When on (packaged desktop), this runs
    ALONGSIDE the router's existing origin+CSRF+session check, so it only needs to
    verify the token — a rogue local process that somehow has the session cookie
    still can't drive the API without the token the shell injected.
    """
    settings = request.app.state.settings
    if not settings.require_local_token:
        return
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    expected = request.app.state.install_token
    if scheme.lower() != "bearer" or not supplied or not secrets.compare_digest(supplied, expected):
        raise ManagerError("invalid_local_token", "A valid local access token is required.", 401)
