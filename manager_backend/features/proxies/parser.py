from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from ...errors import ManagerError


_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


@dataclass(frozen=True, slots=True)
class ParsedProxyValue:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None


def _invalid() -> ManagerError:
    return ManagerError("invalid_proxy", "The proxy value is invalid.", 422)


def _validate_text(value: str) -> str:
    candidate = value.strip()
    if not candidate or candidate != value:
        raise _invalid()
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise _invalid()
    if any(character.isspace() for character in candidate):
        raise _invalid()
    return candidate


def _port(value: str | int | None) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _invalid() from None
    if not 1 <= parsed <= 65535:
        raise _invalid()
    return parsed


def _credentials(username: str | None, password: str | None) -> tuple[str | None, str | None]:
    if (username is None) != (password is None):
        raise _invalid()
    if username is not None and (not username or not password):
        raise _invalid()
    return username, password


def _bare_host_port(value: str) -> tuple[str, int]:
    if value.startswith("["):
        closing = value.find("]")
        if closing < 2 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise _invalid()
        host = value[1:closing]
        port = _port(value[closing + 2 :])
    else:
        if value.count(":") != 1:
            raise _invalid()
        host, raw_port = value.rsplit(":", 1)
        port = _port(raw_port)
    if not host:
        raise _invalid()
    return host.casefold(), port


def parse_proxy(value: str) -> ParsedProxyValue:
    candidate = _validate_text(value)
    if "://" in candidate:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme.casefold() not in _SCHEMES
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise _invalid()
        try:
            port = _port(parsed.port)
        except ValueError:
            raise _invalid() from None
        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None
        username, password = _credentials(username, password)
        return ParsedProxyValue(
            parsed.scheme.casefold(), parsed.hostname.casefold(), port, username, password
        )

    username = password = None
    endpoint = candidate
    if "@" in candidate:
        if candidate.count("@") != 1:
            raise _invalid()
        raw_credentials, endpoint = candidate.split("@", 1)
        if ":" not in raw_credentials:
            raise _invalid()
        username, password = raw_credentials.split(":", 1)
    elif candidate.count(":") == 3 and not candidate.startswith("["):
        host, raw_port, username, password = candidate.split(":", 3)
        endpoint = f"{host}:{raw_port}"
    username, password = _credentials(username, password)
    host, port = _bare_host_port(endpoint)
    return ParsedProxyValue("socks5", host, port, username, password)
