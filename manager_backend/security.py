from __future__ import annotations

import re
import secrets
from uuid import uuid4

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
    request.state.request_id = str(uuid4())
    settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is not None and origin != settings.allowed_origin:
        raise ManagerError("invalid_origin", "This browser origin is not allowed.", 403)

    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    expected = request.app.state.install_token
    if scheme.lower() != "bearer" or not supplied or not secrets.compare_digest(supplied, expected):
        raise ManagerError("invalid_local_token", "A valid local access token is required.", 401)
