"""Authorized-email input parsing: normalize, validate, deduplicate.

The raw pasted text is NEVER logged. This module returns structured results with
masked values only; the full normalized email is handed to the caller solely to
write into CredentialStore. Malformed lines are reported separately (with a
masked value and 1-based source line number) and are never treated as an
account result — a bad input is not an "account not found".
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

# local@domain.tld, no whitespace, at least one dot in the domain.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    line: int
    normalized: str
    masked: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class InvalidEntry:
    line: int
    masked: str
    reason: str  # "malformed"


@dataclass(frozen=True, slots=True)
class DuplicateEntry:
    line: int
    masked: str


@dataclass
class ParsedInput:
    valid: list[ParsedEmail] = field(default_factory=list)
    duplicates: list[DuplicateEntry] = field(default_factory=list)
    invalid: list[InvalidEntry] = field(default_factory=list)
    total_lines: int = 0  # non-blank lines considered (= valid+duplicates+invalid)


def _mask_segment(segment: str) -> str:
    head = segment[:2] if len(segment) > 2 else segment[:1]
    return f"{head}***"


def mask_email(email: str) -> str:
    """Mask a valid email to a display form: `jo***@ex***.com`."""
    local, _, domain = email.partition("@")
    name, dot, tld = domain.rpartition(".")
    if not dot:  # no tld separator (shouldn't happen for validated input)
        return f"{_mask_segment(local)}@{_mask_segment(domain)}"
    return f"{_mask_segment(local)}@{_mask_segment(name)}.{tld}"


def mask_value(value: str) -> str:
    """Mask an arbitrary (possibly invalid) input line."""
    return _mask_segment(value.strip())


def fingerprint(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def worker_count(valid_unique: int, emails_per_profile: int) -> int:
    if valid_unique <= 0:
        return 0
    return math.ceil(valid_unique / emails_per_profile)


def parse_email_input(text: str) -> ParsedInput:
    result = ParsedInput()
    seen: set[str] = set()
    for index, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue  # blank lines are ignored entirely, not counted
        result.total_lines += 1
        if not _EMAIL_RE.match(stripped):
            result.invalid.append(
                InvalidEntry(line=index, masked=mask_value(stripped), reason="malformed")
            )
            continue
        normalized = stripped.lower()
        if normalized in seen:
            result.duplicates.append(
                DuplicateEntry(line=index, masked=mask_email(normalized))
            )
            continue
        seen.add(normalized)
        result.valid.append(
            ParsedEmail(
                line=index,
                normalized=normalized,
                masked=mask_email(normalized),
                fingerprint=fingerprint(normalized),
            )
        )
    return result
