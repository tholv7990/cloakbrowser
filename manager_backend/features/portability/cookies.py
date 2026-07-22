"""Bounded, value-safe cookie format parsing for Manager portability."""

from __future__ import annotations

import io
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import ijson
import tldextract
from ijson import JSONError


MAX_COOKIE_PAYLOAD_BYTES = 10 * 1024 * 1024
MAX_COOKIE_COUNT = 10_000
MAX_COOKIE_WARNINGS = 16
MAX_COOKIE_VALUE_BYTES = 4096
MAX_COOKIE_NAME_BYTES = 256
MAX_COOKIE_DOMAIN_BYTES = 253
MAX_COOKIE_PATH_BYTES = 4096
MAX_COOKIE_EXPIRY_SECONDS = (2**53) - 1

_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_SAME_SITE_VALUES = {
    "none": "None",
    "no_restriction": "None",
    "lax": "Lax",
    "strict": "Strict",
}
_WARNING_CODES = frozenset(
    {
        "invalid_cookie",
        "invalid_domain",
        "invalid_expiry",
        "invalid_host_prefix",
        "invalid_http_only",
        "invalid_name",
        "invalid_netscape_record",
        "invalid_path",
        "invalid_samesite",
        "invalid_secure",
        "invalid_value",
        "insecure_samesite_none",
        "insecure_secure_prefix",
    }
)
# The package's bundled PSL snapshot is used exclusively.  No cache or live fetch
# is allowed while parsing an untrusted cookie import.
_PSL_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)


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


@dataclass(frozen=True)
class _CookieRecord:
    raw: dict[str, Any] | None = None
    error_code: str | None = None


class _CookieValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def parse_cookie_payload(data: Any, format: str) -> CookieParseResult:
    """Parse one supported format into Playwright-compatible cookie dictionaries.

    JSON formats are event-parsed with ``ijson``.  The parser raises as soon as it
    sees the 10,001st cookie's ``start_map`` event, before building that record.
    Individual record failures are reported only as a bounded index/code pair.
    """

    normalized_format = _normalize_format(format)
    payload = _payload_bytes(data)
    records = (
        _iter_netscape_records(payload)
        if normalized_format == "netscape"
        else _iter_json_records(payload, normalized_format)
    )

    accepted: list[dict[str, Any]] = []
    warnings: list[CookieParseWarning] = []
    rejected = 0
    try:
        for index, record in enumerate(records):
            if record.error_code is not None:
                rejected += 1
                _append_warning(warnings, index, record.error_code)
                continue
            try:
                accepted.append(_normalize_cookie(record.raw))
            except _CookieValidationError as error:
                rejected += 1
                _append_warning(warnings, index, error.code)
    except (JSONError, UnicodeDecodeError) as error:
        raise ValueError("invalid_cookie_payload") from error

    return CookieParseResult(
        cookies=accepted,
        warnings=warnings,
        skipped=0,
        rejected=rejected,
    )


def to_netscape(cookies: Iterable[dict[str, Any]]) -> str:
    """Encode normalized cookies as a Netscape HTTP Cookie File.

    Netscape's ``0`` is reserved for session cookies.  A real Unix epoch expiry
    cannot round-trip through the format, so it is rejected rather than changed.
    """

    lines = ["# Netscape HTTP Cookie File"]
    for raw_cookie in cookies:
        try:
            cookie = _normalize_cookie(raw_cookie)
        except _CookieValidationError as error:
            raise ValueError("invalid_cookie_for_export") from error
        if cookie["expires"] == 0:
            raise ValueError("invalid_cookie_for_export")

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


def _normalize_format(format: str) -> str:
    if not isinstance(format, str):
        raise ValueError("unsupported_cookie_format")
    normalized = format.strip().lower()
    if normalized not in {"json", "playwright", "netscape"}:
        raise ValueError("unsupported_cookie_format")
    return normalized


def _payload_bytes(data: Any) -> bytes:
    if isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        try:
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("invalid_cookie_payload") from error
    if len(payload) > MAX_COOKIE_PAYLOAD_BYTES:
        raise ValueError("payload_too_large")
    return payload


def _iter_json_records(payload: bytes, format: str) -> Iterator[_CookieRecord]:
    events = iter(ijson.parse(io.BytesIO(payload)))
    try:
        root_prefix, root_event, _root_value = next(events)
    except StopIteration as error:
        raise ValueError("invalid_cookie_payload") from error
    if root_prefix != "" or root_event not in {"start_array", "start_map"}:
        raise ValueError("invalid_cookie_payload")
    if format == "json" and root_event != "start_map":
        raise ValueError("invalid_cookie_payload")

    envelope = root_event == "start_map"
    item_prefix = "cookies.item" if envelope else "item"
    array_prefix = "cookies" if envelope else ""
    if format == "playwright" and not envelope and root_event != "start_array":
        raise ValueError("invalid_cookie_payload")

    cookie_count = 0
    current: dict[str, Any] | None = None
    current_key: str | None = None
    envelope_keys: set[str] = set()
    cookies_array_started = not envelope
    cookies_array_finished = False
    root_finished = False

    def start_cookie() -> None:
        nonlocal cookie_count
        if cookie_count >= MAX_COOKIE_COUNT:
            raise ValueError("too_many_cookies")
        cookie_count += 1

    for prefix, event, value in events:
        if envelope and prefix == "" and event == "map_key":
            if not isinstance(value, str):
                raise ValueError("invalid_cookie_payload")
            envelope_keys.add(value)
            if value != "cookies":
                raise ValueError("invalid_cookie_payload")
            continue
        if envelope and prefix == array_prefix and event == "start_array":
            if not envelope_keys or cookies_array_started:
                raise ValueError("invalid_cookie_payload")
            cookies_array_started = True
            continue
        if prefix == array_prefix and event == "end_array":
            cookies_array_finished = True
            continue
        if envelope and prefix == "" and event == "end_map":
            root_finished = True
            continue

        if prefix == item_prefix and event == "start_map":
            if not cookies_array_started or current is not None:
                raise ValueError("invalid_cookie_payload")
            start_cookie()
            current = {}
            current_key = None
            continue
        if prefix == item_prefix and event in {"string", "number", "boolean", "null", "start_array"}:
            if not cookies_array_started:
                raise ValueError("invalid_cookie_payload")
            start_cookie()
            yield _CookieRecord(error_code="invalid_cookie")
            continue
        if prefix == item_prefix and event == "map_key" and current is not None:
            current_key = value if isinstance(value, str) else None
            continue
        if prefix == item_prefix and event == "end_map" and current is not None:
            yield _CookieRecord(raw=current)
            current = None
            current_key = None
            continue
        if current is not None and current_key is not None:
            direct_field_prefix = f"{item_prefix}.{current_key}"
            if prefix == direct_field_prefix and event in {"string", "number", "boolean", "null"}:
                current[current_key] = value
            elif prefix == direct_field_prefix and event in {"start_array", "start_map"}:
                # Keep the value typed-but-invalid without serializing it into a warning.
                current[current_key] = object()

    if current is not None or not cookies_array_started or not cookies_array_finished:
        raise ValueError("invalid_cookie_payload")
    if envelope and (envelope_keys != {"cookies"} or not root_finished):
        raise ValueError("invalid_cookie_payload")
    if not envelope and not cookies_array_finished:
        raise ValueError("invalid_cookie_payload")


def _iter_netscape_records(payload: bytes) -> Iterator[_CookieRecord]:
    text = payload.decode("utf-8")
    record_count = 0
    for line in io.StringIO(text):
        line = line.rstrip("\r\n")
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if record_count >= MAX_COOKIE_COUNT:
            raise ValueError("too_many_cookies")
        record_count += 1

        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :]
        fields = line.split("\t")
        if len(fields) != 7:
            yield _CookieRecord(error_code="invalid_netscape_record")
            continue
        domain, include_subdomains, path, secure, expiry_text, name, value = fields
        if include_subdomains.upper() not in {"TRUE", "FALSE"} or secure.upper() not in {
            "TRUE",
            "FALSE",
        }:
            yield _CookieRecord(error_code="invalid_netscape_record")
            continue
        if not expiry_text.isdecimal() or len(expiry_text) > len(
            str(MAX_COOKIE_EXPIRY_SECONDS)
        ):
            yield _CookieRecord(error_code="invalid_expiry")
            continue
        try:
            expiry = int(expiry_text)
        except ValueError:
            yield _CookieRecord(error_code="invalid_expiry")
            continue
        if expiry > MAX_COOKIE_EXPIRY_SECONDS:
            yield _CookieRecord(error_code="invalid_expiry")
            continue
        if include_subdomains.upper() == "TRUE" and not domain.startswith("."):
            domain = f".{domain}"
        elif include_subdomains.upper() == "FALSE":
            domain = domain.lstrip(".")
        yield _CookieRecord(
            raw={
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                # Netscape reserves zero for a session cookie.
                "expires": -1 if expiry == 0 else expiry,
                "secure": secure.upper() == "TRUE",
                "httpOnly": http_only,
            }
        )


def _append_warning(
    warnings: list[CookieParseWarning], index: int, code: str
) -> None:
    if len(warnings) < MAX_COOKIE_WARNINGS:
        warnings.append(
            CookieParseWarning(
                index=index,
                code=code if code in _WARNING_CODES else "invalid_cookie",
            )
        )


def _normalize_cookie(raw_cookie: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw_cookie, dict):
        raise _CookieValidationError("invalid_cookie")

    name = raw_cookie.get("name")
    if not isinstance(name, str) or not name or not _is_limited_utf8(name, MAX_COOKIE_NAME_BYTES):
        raise _CookieValidationError("invalid_name")
    if not _COOKIE_NAME_RE.fullmatch(name):
        raise _CookieValidationError("invalid_name")

    value = raw_cookie.get("value")
    if not isinstance(value, str) or not _is_limited_utf8(value, MAX_COOKIE_VALUE_BYTES):
        raise _CookieValidationError("invalid_value")
    if _has_unsafe_netscape_text(value):
        raise _CookieValidationError("invalid_value")

    domain = raw_cookie.get("domain")
    if not _is_valid_domain(domain):
        raise _CookieValidationError("invalid_domain")

    path = raw_cookie.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/"):
        raise _CookieValidationError("invalid_path")
    if not _is_limited_utf8(path, MAX_COOKIE_PATH_BYTES) or _has_unsafe_netscape_text(path):
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
    if name.startswith("__Secure-") and not secure:
        raise _CookieValidationError("insecure_secure_prefix")
    if name.startswith("__Host-") and (not secure or path != "/" or domain.startswith(".")):
        raise _CookieValidationError("invalid_host_prefix")

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


def _has_unsafe_netscape_text(value: str) -> bool:
    return any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or character in {"\u2028", "\u2029"}
        for character in value
    )


def _is_valid_domain(domain: Any) -> bool:
    if not isinstance(domain, str) or not domain or not _is_limited_utf8(domain, MAX_COOKIE_DOMAIN_BYTES):
        return False
    if _has_unsafe_netscape_text(domain):
        return False
    is_subdomain_cookie = domain.startswith(".")
    hostname = domain[1:] if is_subdomain_cookie else domain
    if not hostname or hostname.endswith(".") or any(character.isspace() for character in hostname):
        return False

    if "%" in hostname:
        return False
    is_bracketed = hostname.startswith("[") and hostname.endswith("]")
    if hostname.startswith("[") != hostname.endswith("]"):
        return False
    ip_hostname = hostname[1:-1] if is_bracketed else hostname
    try:
        ip_address = ipaddress.ip_address(ip_hostname)
    except ValueError:
        pass
    else:
        if isinstance(ip_address, ipaddress.IPv6Address):
            return is_bracketed and not is_subdomain_cookie
        return not is_bracketed and not is_subdomain_cookie

    if hostname.lower() == "localhost":
        return not is_subdomain_cookie
    labels = hostname.split(".")
    if not all(_DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        return False
    extracted = _PSL_EXTRACT(hostname)
    return not (not extracted.domain and bool(extracted.suffix))


def _normalize_expiry(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _CookieValidationError("invalid_expiry")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise _CookieValidationError("invalid_expiry")
    expires = int(value)
    if expires != -1 and not 0 <= expires <= MAX_COOKIE_EXPIRY_SECONDS:
        raise _CookieValidationError("invalid_expiry")
    return float(expires)


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
