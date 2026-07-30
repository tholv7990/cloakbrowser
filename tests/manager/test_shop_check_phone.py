"""Calling-code parser: masked phone hint -> geography with honest confidence.

We only ever see a masked number (a leading calling code + a trailing suffix),
never the national number, so a shared numbering plan can only be `ambiguous` —
resolving it would be a guess. Proxy geography is never consulted here.
"""

from __future__ import annotations

from manager_backend.features.shop_check.phone import lookup_calling_code, parse_phone_hint


def test_exact_single_country():
    info = parse_phone_hint("+84 ••• ••34")
    assert info.prefix == "+84"
    assert info.suffix == "34"
    assert info.country_code == "VN"
    assert info.country_name == "Vietnam"
    assert info.confidence == "exact"
    assert info.region_name is None


def test_nanp_is_ambiguous_never_guessed():
    info = parse_phone_hint("+1 (•••) •••-••34")
    assert info.prefix == "+1"
    assert info.confidence == "ambiguous"
    assert info.country_code is None
    assert info.country_name is None
    assert info.region_name and "North American" in info.region_name


def test_russia_kazakhstan_shared_plan_is_ambiguous():
    info = lookup_calling_code("+7")
    assert info.confidence == "ambiguous"
    assert info.country_code is None
    assert "Russia" in info.region_name and "Kazakhstan" in info.region_name


def test_longest_prefix_match_does_not_resolve_nanp_territory():
    # A partially-unmasked NANP number (with an area code) still resolves only to
    # the +1 plan, never to a specific territory — we don't guess from digits.
    info = parse_phone_hint("+1876••••34")  # 876 = Jamaica area code
    assert info.prefix == "+1"
    assert info.confidence == "ambiguous"


def test_unknown_calling_code():
    info = parse_phone_hint("+999••34")
    assert info.confidence == "unknown"
    assert info.country_code is None
    assert info.country_name is None


def test_no_plus_means_unknown_geography_but_keeps_suffix():
    # Without a '+' the leading digits could be a local trunk prefix, not a
    # calling code. We refuse to infer a country (and never fall back to proxy IP).
    info = parse_phone_hint("0912 345 634")
    assert info.confidence == "unknown"
    assert info.country_code is None
    assert info.suffix == "634"


def test_empty_and_junk_are_unknown():
    for raw in ["", "   ", "no digits here", "+"]:
        info = parse_phone_hint(raw)
        assert info.confidence == "unknown"
        assert info.country_code is None
        assert info.prefix is None or info.prefix.startswith("+")


def test_never_stores_the_national_number_middle():
    full = "+1 415 555 0134"
    info = parse_phone_hint(full)
    fields = [info.prefix, info.suffix, info.country_code, info.country_name, info.region_name]
    # The distinctive middle digits must not survive anywhere.
    assert all("5550" not in (value or "") for value in fields)
    assert all("415555" not in (value or "") for value in fields)
    assert info.suffix == "0134"


def test_uk_is_exact_gb():
    info = lookup_calling_code("+44")
    assert info.confidence == "exact"
    assert info.country_code == "GB"
