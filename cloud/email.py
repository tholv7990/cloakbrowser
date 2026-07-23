"""Transactional email delivery (verification + password reset).

A tiny interface so the provider (SES/Postmark/Resend/…) is swappable and tests can
capture what would be sent. The console sender logs that a mail was sent but NEVER
the token (it's a secret).
"""

from __future__ import annotations

import logging

_logger = logging.getLogger("cloud.email")


class EmailSender:
    def send_verification(self, *, email: str, token: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def send_password_reset(self, *, email: str, token: str) -> None:  # pragma: no cover
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    def send_verification(self, *, email: str, token: str) -> None:
        _logger.info("verification email queued for %s", email)

    def send_password_reset(self, *, email: str, token: str) -> None:
        _logger.info("password-reset email queued for %s", email)


class RecordingEmailSender(EmailSender):
    """Test double — keeps (kind, email, token) so a test can act on the link."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_verification(self, *, email: str, token: str) -> None:
        self.sent.append(("verify", email, token))

    def send_password_reset(self, *, email: str, token: str) -> None:
        self.sent.append(("reset", email, token))

    def last_token(self, kind: str, email: str) -> str | None:
        for k, e, token in reversed(self.sent):
            if k == kind and e == email:
                return token
        return None
