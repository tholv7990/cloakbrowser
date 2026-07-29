"""Centralized error sanitization for the Shop-check feature.

Every error string persisted to a run/worker/email row or surfaced in an API
response must pass through `sanitize_error`. It redacts caller-supplied secrets
(the full email, the proxy password) AND, as defense in depth, any email-shaped
or proxy-URL-credential-shaped substring — so a secret that reaches an error via
a path we did not anticipate is still scrubbed. Output is length-capped.
"""

from __future__ import annotations

import re

_MAX_LENGTH = 1000
_REDACTION = "***"

# An email address anywhere in free text.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# The `user:password@host` credential portion of a proxy URL (socks5h/http(s)).
_PROXY_CRED_RE = re.compile(r"(?i)\b(socks5h?|https?)://[^\s/@]+@")


def sanitize_error(message: object, *secrets: str | None, limit: int = _MAX_LENGTH) -> str:
    """Redact secrets and secret-shaped substrings from `message`, then cap length."""
    text = str(message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTION)
    text = _PROXY_CRED_RE.sub(lambda m: f"{m.group(1)}://{_REDACTION}@", text)
    text = _EMAIL_RE.sub(_REDACTION, text)
    return text[:limit]
