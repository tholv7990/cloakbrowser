"""Bounded, value-safe cookie format parsing for Manager portability."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


MAX_COOKIE_PAYLOAD_BYTES = 10 * 1024 * 1024
MAX_COOKIE_COUNT = 10_000
MAX_COOKIE_WARNINGS = 16
MAX_COOKIE_VALUE_BYTES = 4096
MAX_COOKIE_NAME_BYTES = 256
MAX_COOKIE_DOMAIN_BYTES = 253
MAX_COOKIE_PATH_BYTES = 4096

_COOKIE_NAME_RE = re.compile(r'^[^\x00-\x20\x7f()<>@,;:\\"/\[\]?={}]+$')
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_SAME_SITE_VALUES = {
    "none": "None",
    "no_restriction": "None",
    "lax": "Lax",
    "strict": "Strict",
}


@dataclass(frozen=True)
class CookieParseWarning:
    """A stable, indexed warning which deliberately omits cookie contents."""

    index: int
    code: str

    def model_dump(self) -> dict[str, Any]:
        return {"index": self.index, "code": self.code}


@dataclass
class CookieParseResult:
    """Normalized Playwright cookies plus bounded, field-safe diagnostics."""

    cookies: list[dict[str, Any]]
    warnings: list[CookieParseWarning]
    skipped: int = 0
    rejected: int = 0

    def model_dump(self) -> dict[str, Any]:
        return {
            "cookies": self.cookies,
            "warnings": [warning.model_dump() for warning in self.warnings],
            "skipped": self.skipped,
            "rejected": self.rejected,
        }


def parse_cookie_payload(data: Any, format: str) -> CookieParseResult:
    """Parse one supported format into Playwright-compatible cookie dictionaries.

    ``data`` may be decoded JSON, UTF-8 JSON text/bytes, or Netscape text/bytes.
    Invalid individual records are rejected with a bounded warning that contains only
    the record index and a stable code; it can never contain a cookie value.
    """

    normalized_format = _normalize_format(format)
    payload = _coerce_payload(data)
    _ensure_payload_size(payload)

    if normalized_format == "netscape":
        raw_cookies = _parse_netscape(payload)
    else:
        raw_cookies = _parse_json(payload, normalized_format)

    if len(raw_cookies) > MAX_COOKIE_COUNT:
        raise ValueError("too_many_cookies")

    accepted: list[dict[str, Any]] = []
    warnings: list[CookieParseWarning] = []
    rejected = 0
    for index, raw_cookie in enumerate(raw_cookies):
        try:
            accepted.append(_normalize_cookie(raw_cookie))
        except _CookieValidationError as error:
            rejected += 1
            if len(warnings) < MAX_COOKIE_WARNINGS:
                warnings.append(CookieParseWarning(index=index, code=error.code))

    return CookieParseResult(
        cookies=accepted,
        warnings=warnings,
        skipped=0,
        rejected=rejected,
    )


def to_netscape(cookies: Iterable[dict[str, Any]]) -> str:
    """Encode normalized cookies as a Netscape HTTP Cookie File.

    The function revalidates records before serializing so a caller cannot inject
    a line through an untrusted cookie value or field.
    """

    lines = ["# Netscape HTTP Cookie File"]
    for raw_cookie in cookies:
        try:
            cookie = _normalize_cookie(raw_cookie)
        except _CookieValidationError as error:
            raise ValueError("invalid_cookie_for_export") from error

        domain = cookie["domain"]
        if cookie["httpOnly"]:
            domain = f"#HttpOnly_{domain}"
        include_subdomains = "TRUE" if cookie["domain"].startswith(".") else "FALSE"
        expires = int(cookie["expires"]) if cookie["expires"] > 0 else 0
        lines.append(
            "\t".join(
                (
                    domain,
                    include_subdomains,
                    cookie["path"],
                    "TRUE" if cookie["secure"] else "FALSE",
                    str(expires),
                    cookie["name"],
                    cookie["value"],
                )
            )
        )
    return "\n".join(lines) + "\n"


class _CookieValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _normalize_format(format: str) -> str:
    if not isinstance(format, str):
        raise ValueError("unsupported_cookie_format")
    normalized = format.strip().lower()
    if normalized not in {"json", "playwright", "netscape"}:
        raise ValueError("unsupported_cookie_format")
    return normalized


def _coerce_payload(data: Any) -> str | Any:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("invalid_cookie_payload") from error
    return data


def _ensure_payload_size(payload: str | Any) -> None:
    if isinstance(payload, str):
        size = len(payload.encode("utf-8"))
    else:
        try:
            size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("invalid_cookie_payload") from error
    if size > MAX_COOKIE_PAYLOAD_BYTES:
        raise ValueError("payload_too_large")


def _parse_json(payload: str | Any, format: str) -> list[Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("invalid_cookie_payload") from error

    if format == "json":
        if not isinstance(payload, dict) or set(payload) != {"cookies"}:
            raise ValueError("invalid_cookie_payload")
        cookies = payload["cookies"]
    elif isinstance(payload, list):
        cookies = payload
    elif isinstance(payload, dict) and set(payload) == {"cookies"}:
        # Browser storage-state exports commonly carry this envelope.
        cookies = payload["cookies"]
    else:
        raise ValueError("invalid_cookie_payload")

    if not isinstance(cookies, list):
        raise ValueError("invalid_cookie_payload")
    return cookies


def _parse_netscape(payload: str | Any) -> list[dict[str, Any]]:
    if not isinstance(payload, str):
        raise ValueError("invalid_cookie_payload")

    cookies: list[dict[str, Any]] = []
    for line in payload.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :]
        fields = line.split("\t")
        if len(fields) != 7:
            cookies.append({"_invalid_code": "invalid_netscape_record"})
            continue
        domain, include_subdomains, path, secure, expires, name, value = fields
        if include_subdomains.upper() not in {"TRUE", "FALSE"}:
            cookies.append({"_invalid_code": "invalid_netscape_record"})
            continue
        if secure.upper() not in {"TRUE", "FALSE"}:
            cookies.append({"_invalid_code": "invalid_netscape_record"})
            continue
        try:
            expiry = int(expires)
        except ValueError:
            cookies.append({"_invalid_code": "invalid_expiry"})
            continue
        if expiry < 0:
            cookies.append({"_invalid_code": "invalid_expiry"})
            continue
        if include_subdomains.upper() == "TRUE" and not domain.startswith("."):
            domain = f".{domain}"
        elif include_subdomains.upper() == "FALSE":
            domain = domain.lstrip(".")
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": -1 if expiry == 0 else expiry,
                "secure": secure.upper() == "TRUE",
                "httpOnly": http_only,
            }
        )
    return cookies


def _normalize_cookie(raw_cookie: Any) -> dict[str, Any]:
    if not isinstance(raw_cookie, dict):
        raise _CookieValidationError("invalid_cookie")
    invalid_code = raw_cookie.get("_invalid_code")
    if invalid_code is not None:
        raise _CookieValidationError(
            invalid_code if isinstance(invalid_code, str) else "invalid_cookie"
        )

    name = raw_cookie.get("name")
    if not isinstance(name, str) or not name or not _is_limited_utf8(name, MAX_COOKIE_NAME_BYTES):
        raise _CookieValidationError("invalid_name")
    if not _COOKIE_NAME_RE.fullmatch(name):
        raise _CookieValidationError("invalid_name")

    value = raw_cookie.get("value")
    if not isinstance(value, str) or not _is_limited_utf8(value, MAX_COOKIE_VALUE_BYTES):
        raise _CookieValidationError("invalid_value")
    if any(character in value for character in ("\r", "\n", "\t", "\x00")):
        raise _CookieValidationError("invalid_value")

    domain = raw_cookie.get("domain")
    if not _is_valid_domain(domain):
        raise _CookieValidationError("invalid_domain")

    path = raw_cookie.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/"):
        raise _CookieValidationError("invalid_path")
    if not _is_limited_utf8(path, MAX_COOKIE_PATH_BYTES) or any(
        character in path for character in ("\r", "\n", "\t", "\x00")
    ):
        raise _CookieValidationError("invalid_path")

    expires = _normalize_expiry(raw_cookie.get("expires", raw_cookie.get("expirationDate", -1)))
    secure = _strict_bool(raw_cookie.get("secure", False), "invalid_secure")
    http_only = _strict_bool(
        raw_cookie.get("httpOnly", raw_cookie.get("http_only", False)),
        "invalid_http_only",
    )
    same_site = _normalize_same_site(raw_cookie.get("sameSite", raw_cookie.get("same_site")))
    if same_site == "None" and not secure:
        raise _CookieValidationError("insecure_samesite_none")

    normalized = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "expires": expires,
        "secure": secure,
        "httpOnly": http_only,
    }
    if same_site is not None:
        normalized["sameSite"] = same_site
    return normalized


def _is_limited_utf8(value: str, limit: int) -> bool:
    return len(value.encode("utf-8")) <= limit


def _is_valid_domain(domain: Any) -> bool:
    if not isinstance(domain, str) or not domain or not _is_limited_utf8(domain, MAX_COOKIE_DOMAIN_BYTES):
        return False
    hostname = domain[1:] if domain.startswith(".") else domain
    if not hostname or hostname.endswith(".") or any(character.isspace() for character in hostname):
        return False
    if any(character in hostname for character in ("/", "\\", ":", "@", "\x00")):
        return False
    if hostname.lower() == "localhost":
        return True
    labels = hostname.split(".")
    return all(_DOMAIN_LABEL_RE.fullmatch(label) for label in labels)


def _normalize_expiry(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _CookieValidationError("invalid_expiry")
    expires = float(value)
    if not math.isfinite(expires) or expires < -1:
        raise _CookieValidationError("invalid_expiry")
    return expires


def _strict_bool(value: Any, code: str) -> bool:
    if not isinstance(value, bool):
        raise _CookieValidationError(code)
    return value


def _normalize_same_site(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _CookieValidationError("invalid_samesite")
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"", "unspecified"}:
        return None
    try:
        return _SAME_SITE_VALUES[normalized]
    except KeyError as error:
        raise _CookieValidationError("invalid_samesite") from error
