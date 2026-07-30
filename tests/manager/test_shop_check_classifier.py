"""Deterministic Shop-page classifier: HTML in, one terminal outcome out.

Fixtures live next to the classifier; each file is named `<result>__<lang>.html`
so the expected outcome is the part before `__`. `unknown__*.html` files are the
no-match / conflict / changed-markup cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manager_backend.features.shop_check import classifier
from manager_backend.features.shop_check.classifier import classify

_FIXTURES = Path(classifier.__file__).parent / "fixtures"
_CASES = sorted(_FIXTURES.glob("*.html"))


@pytest.mark.parametrize("path", _CASES, ids=lambda p: p.name)
def test_fixture_classifies_to_its_named_outcome(path: Path):
    expected = path.name.split("__")[0]
    assert classify(path.read_text(encoding="utf-8")).result == expected


def test_empty_and_whitespace_are_unknown():
    assert classify("").result == "unknown"
    assert classify("   \n\t ").result == "unknown"
    assert classify("<html><body></body></html>").result == "unknown"


def test_conflicting_signals_are_unknown():
    # Two different terminal outcomes both fire -> refuse to guess.
    html = (
        "<p>We couldn't find an account with that email address.</p>"
        "<p>Please enter a valid email address.</p>"
    )
    assert classify(html).result == "unknown"


def test_phone_otp_requires_more_than_one_signal():
    # A lone incidental "phone number" mention (e.g. a support footer) must NOT
    # be classified as phone OTP; a real OTP page carries a code-delivery signal.
    incidental = "<footer>Call our phone number for help.</footer>"
    assert classify(incidental).result != "phone_otp_required"

    real = (
        "<h1>Enter your code</h1>"
        "<p>We texted a code to the phone number ending in 34.</p>"
    )
    assert classify(real).result == "phone_otp_required"


def test_email_otp_needs_code_delivery_not_a_bare_form():
    # The initial sign-in form says "your email" but has sent no code -> unknown,
    # never email_otp_required.
    form = (
        "<h1>Sign in</h1><label>Enter your email address</label>"
        "<input type='email' />"
    )
    assert classify(form).result != "email_otp_required"


def test_output_carries_only_constant_signal_phrases_never_page_text():
    # The page echoes the entered email; the classifier must surface only its own
    # constant signal phrases, never scraped page text / the email.
    sentinel = "sentinel.person@corp-example.com"
    html = (
        f"<input value='{sentinel}' />"
        "<p>We couldn't find an account with that email address.</p>"
    )
    result = classify(html)
    assert result.result == "account_not_found"
    blob = " ".join(result.signals)
    assert sentinel not in blob
    assert all(signal in classifier.SIGNALS["account_not_found"] for signal in result.signals)


def test_case_and_whitespace_insensitive():
    html = "<P>WE  COULDN'T\n FIND   an ACCOUNT with that email address.</P>"
    assert classify(html).result == "account_not_found"


def test_script_and_style_content_is_ignored():
    # A signal phrase buried in a <script> string must not drive classification.
    html = (
        "<style>.x{content:'you are signed in'}</style>"
        "<script>var m = \"we couldn't find an account\";</script>"
        "<h1>Shop</h1>"
    )
    assert classify(html).result == "unknown"
