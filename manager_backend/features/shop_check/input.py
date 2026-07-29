"""Authorized-email input parsing: validate, canonicalize, deduplicate.

The raw pasted text is NEVER logged. This module returns structured results with
masked values only; the full canonical email is handed to the caller solely to
write into CredentialStore. Malformed lines are reported separately (with a
masked value and 1-based source line number) and are never treated as an
account result — a bad input is not an "account not found".

Canonical form (used for dedup, fingerprint, and the CredentialStore value):

    <submitted local part>@<lowercased domain>

That is: the domain is lowercased/IDNA-normalized (email domains are
case-insensitive) but the local part is preserved as submitted (local parts are
case-sensitive per RFC 5321). Consequently deduplication is case-INsensitive on
the domain and case-SENSITIVE on the local part — distinct local parts are never
merged. Validation uses the project's `email_validator` dependency, which
rejects malformed domains, consecutive dots, missing local/domain parts, and
whitespace.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email


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


def canonicalize(raw: str) -> str | None:
    """Return the canonical form of a submitted address, or None if invalid."""
    try:
        result = validate_email(raw, check_deliverability=False)
    except EmailNotValidError:
        return None
    return result.normalized  # local part preserved, domain lowercased/normalized


def fingerprint(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        canonical = canonicalize(stripped)
        if canonical is None:
            result.invalid.append(
                InvalidEntry(line=index, masked=mask_value(stripped), reason="malformed")
            )
            continue
        if canonical in seen:
            result.duplicates.append(
                DuplicateEntry(line=index, masked=mask_email(canonical))
            )
            continue
        seen.add(canonical)
        result.valid.append(
            ParsedEmail(
                line=index,
                normalized=canonical,
                masked=mask_email(canonical),
                fingerprint=fingerprint(canonical),
            )
        )
    return result
