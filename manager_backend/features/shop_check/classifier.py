"""Deterministic Shop-page classifier.

Turns a page's HTML into exactly one terminal outcome using semantic text
signals in English and Vietnamese. Rules:

- Strip `<script>`/`<style>` bodies and all tags, unescape entities, lowercase,
  and collapse whitespace — so a signal buried in a script string or attribute
  never drives the result.
- An outcome "fires" when at least `_THRESHOLD[outcome]` of its signal phrases
  appear in that text. `phone_otp_required` needs two (a bare "phone number"
  mention must not classify a support footer as OTP).
- Exactly one outcome fired -> that outcome. Zero, or more than one (conflicting
  markup) -> `unknown`. Changed markup that matches nothing is also `unknown`.

The returned `signals` are our own constant phrases only — never scraped page
text — so a classification result can be logged without leaking the email.

ponytail: substring signal matching, not a DOM/ML model. Ceiling: Shop can
reword copy and break a phrase; the fixtures pin the current wording and
`unknown` is the safe default. Upgrade path is per-outcome scoring or
attribute/DOM signals if false-`unknown`s show up against live pages.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

# Signal phrases per outcome, already lowercased. Vocabularies are kept disjoint
# across outcomes so a normal page fires exactly one; overlap would (correctly)
# surface as a conflict -> unknown.
SIGNALS: dict[str, tuple[str, ...]] = {
    "phone_otp_required": (
        # EN — code delivered to a phone
        "texted a code",
        "text message",
        "phone number ending",
        "code to the phone",
        "sent a code to your phone",
        "resend sms",
        "phone number",
        # VI
        "gửi mã đến điện thoại",
        "điện thoại kết thúc bằng",
        "qua tin nhắn",
        "tin nhắn",
        "số điện thoại",
    ),
    "email_otp_required": (
        # EN — code delivered to an email (a bare "enter your email" form is NOT this)
        "sent a code to your email",
        "check your email for",
        "we emailed you a code",
        "code to your email",
        "resend code to your email",
        # VI
        "gửi mã đến email",
        "kiểm tra email để lấy mã",
    ),
    "login_success": (
        # EN — markers only present once authenticated
        "log out",
        "sign out",
        "logout",
        "you're signed in",
        "welcome back",
        # VI
        "đăng xuất",
        "chào mừng trở lại",
    ),
    "account_not_found": (
        # EN
        "couldn't find an account",
        "could not find an account",
        "no account with that email",
        "isn't associated with an account",
        "no account found",
        # VI
        "không tìm thấy tài khoản",
        "tài khoản không tồn tại",
    ),
    "email_rejected": (
        # EN
        "enter a valid email",
        "valid email address",
        "invalid email",
        "email is invalid",
        # VI
        "email hợp lệ",
        "email không hợp lệ",
    ),
    "captcha_or_challenge": (
        # EN
        "captcha",
        "verify you are human",
        "are you a robot",
        "checking your browser",
        "security check",
        "unusual activity",
        "cloudflare",
        # VI
        "xác minh bạn là người",
        "kiểm tra bảo mật",
    ),
}

# Minimum distinct signal matches for an outcome to fire. phone OTP demands two
# so a single incidental "phone number" cannot trigger it.
_THRESHOLD: dict[str, int] = {"phone_otp_required": 2}

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Classification:
    result: str
    # Constant signal phrases (from SIGNALS) that matched — safe to log; never
    # contains scraped page text or the email.
    signals: tuple[str, ...] = ()


def _visible_text(page_html: str) -> str:
    without_code = _SCRIPT_STYLE.sub(" ", page_html)
    text = _TAG.sub(" ", without_code)
    text = _html.unescape(text)
    return _WHITESPACE.sub(" ", text).strip().lower()


def classify(page_html: str) -> Classification:
    """Classify a Shop page into one terminal outcome or `unknown`."""
    text = _visible_text(page_html or "")
    if not text:
        return Classification("unknown")

    fired: list[str] = []
    matched: list[str] = []
    for outcome, phrases in SIGNALS.items():
        hits = [phrase for phrase in phrases if phrase in text]
        if len(hits) >= _THRESHOLD.get(outcome, 1):
            fired.append(outcome)
            matched.extend(hits)

    if len(fired) != 1:
        # Zero signals (changed/blank markup) or conflicting outcomes -> refuse.
        return Classification("unknown")
    outcome = fired[0]
    return Classification(outcome, tuple(matched))
