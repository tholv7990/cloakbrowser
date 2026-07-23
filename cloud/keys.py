"""Activation-key generation and verification.

A key is high-entropy random, shown to the buyer exactly once, and stored ONLY as
a keyed HMAC verifier (``HMAC-SHA256(pepper, normalized_key)``). HMAC — not a slow
password hash — is correct here because the key already carries ~120 bits of
entropy, and it allows a constant-time, indexed lookup at redemption. The
``pepper`` lives in the server's secret manager, so a database leak alone cannot
reverse a verifier back to a key.

Format: ``PLASMA-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`` — 24 Crockford Base32 symbols
(120 bits), which excludes the ambiguous I/L/O/U so it survives being read aloud or
retyped. Normalization maps the lenient Crockford letters back so a human typo of
O→0 / I→1 / L→1 still verifies.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Crockford Base32 alphabet (no I, L, O, U).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_PREFIX = "PLASMA"
_KEY_BYTES = 15  # 120 bits -> exactly 24 Base32 symbols
_GROUP = 4


def normalize_email(email: str) -> str:
    """Canonical email for storage + case-insensitive uniqueness."""
    return email.strip().lower()


def _b32_encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    bits = len(data) * 8
    return "".join(_CROCKFORD[(n >> shift) & 0x1F] for shift in range(bits - 5, -1, -5))


def generate_activation_key() -> tuple[str, dict[str, str]]:
    """Return ``(display_key, parts)``. ``display_key`` is shown to the buyer ONCE
    and never persisted. ``parts`` carries the non-secret row fields."""
    body = _b32_encode(secrets.token_bytes(_KEY_BYTES))  # 24 symbols
    groups = [body[i : i + _GROUP] for i in range(0, len(body), _GROUP)]
    display = f"{_PREFIX}-" + "-".join(groups)
    return display, {"lookup_prefix": f"{_PREFIX}-{groups[0]}", "last4": body[-_GROUP:]}


def normalize_key(key: str) -> str:
    """Canonicalize a user-typed key for verifier computation: drop separators and
    the prefix, uppercase, and apply Crockford's lenient letter mapping."""
    stripped = key.strip().upper().replace("-", "").replace(" ", "")
    if stripped.startswith(_PREFIX):
        stripped = stripped[len(_PREFIX) :]
    return stripped.translate(str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V"}))


def key_verifier(key: str, pepper: bytes) -> str:
    """The only stored representation of a key: ``HMAC-SHA256(pepper, normalized)``.
    Constant to compute, safe to index, and useless without the pepper."""
    if not pepper:
        raise ValueError("activation-key pepper must be non-empty")
    normalized = normalize_key(key).encode("ascii")
    return hmac.new(pepper, normalized, hashlib.sha256).hexdigest()
