"""Tests for deterministic proxy-quality report models."""

import pytest

from benchmarks.proxy_quality_models import (
    Confidence,
    NetworkType,
    Reputation,
    Suitability,
    assert_no_secrets,
    classify_network,
    redact_proxy,
    summarize_report,
)


def test_report_enums_are_string_values():
    assert NetworkType.MOBILE == "mobile"
    assert NetworkType.RESIDENTIAL_OR_ISP == "residential_or_isp"
    assert Confidence.HIGH == "high"
    assert Reputation.CLEAN_OBSERVED == "clean_observed"
    assert Suitability.YES == "yes"
    assert Suitability.UNCERTAIN == "uncertain"


def test_two_mobile_signals_are_high_confidence():
    result = classify_network([
        {"source": "ipinfo", "is_mobile": True, "carrier": "Example Mobile"},
        {"source": "asn", "asn_type": "isp", "mcc": "452"},
    ])
    assert result["type"] == "mobile"
    assert result["type_confidence"] == "high"
    assert result["conflicts"] == []
    assert [item["source"] for item in result["evidence"]] == ["ipinfo", "asn"]


def test_hosting_asn_name_heuristic_is_low_confidence():
    result = classify_network([
        {"source": "sapics", "asn": "AS64500", "organization": "Example Cloud Hosting"},
    ])
    assert result["type"] == "datacenter_or_hosting"
    assert result["type_confidence"] == "low"


def test_asn_name_heuristics_do_not_outweigh_structured_mobile_evidence():
    result = classify_network([
        {"source": "ipinfo", "is_mobile": True},
        {"source": "asn", "mcc": "452"},
        {"source": "name-one", "organization": "Example Cloud"},
        {"source": "name-two", "organization": "Example Hosting"},
    ])
    assert result == {
        "type": "mobile",
        "type_confidence": "low",
        "conflicts": ["mobile", "datacenter_or_hosting"],
        "evidence": result["evidence"],
    }


def test_structured_isp_signal_is_residential_or_isp_with_medium_confidence():
    result = classify_network([
        {
            "source": "ipinfo",
            "asn": "AS64510",
            "asn_name": "Example Access Network",
            "asn_type": "isp",
            "is_mobile": False,
            "is_hosting": False,
        }
    ])

    assert result["type"] == "residential_or_isp"
    assert result["type_confidence"] == "medium"
    assert result["conflicts"] == []
    assert result["evidence"] == [
        {
            "source": "ipinfo",
            "asn": "AS64510",
            "organization": "Example Access Network",
            "category": "residential_or_isp",
            "flags": {
                "asn_type": "isp",
                "is_hosting": False,
                "is_mobile": False,
            },
        }
    ]


def test_generic_backbone_asn_remains_unknown_but_is_retained_as_evidence():
    result = classify_network([
        {"source": "sapics", "asn": 3257, "asn_name": "GTT-BACKBONE GTT"}
    ])

    assert result == {
        "type": "unknown",
        "type_confidence": "low",
        "conflicts": [],
        "evidence": [
            {
                "source": "sapics",
                "asn": 3257,
                "organization": "GTT-BACKBONE GTT",
                "category": "unknown",
                "flags": {},
            }
        ],
    }


@pytest.mark.parametrize("bad_value", [{}, [], object()])
def test_empty_or_nonscalar_mobile_fields_are_not_evidence(bad_value):
    result = classify_network([
        {"source": "provider", "carrier": bad_value, "mcc": bad_value, "mnc": bad_value}
    ])

    assert result["type"] == "unknown"
    assert result["evidence"][0]["category"] == "unknown"


def test_organization_telecom_is_not_mobile_evidence():
    result = classify_network([
        {"source": "lookup", "organization": "Example Telecom Services"},
    ])
    assert result["type"] == "unknown"
    assert result["type_confidence"] == "low"
    assert result["conflicts"] == []
    assert result["evidence"][0]["organization"] == "Example Telecom Services"


def test_clean_observed_requires_all_live_signals():
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "classification": {"type": "mobile", "type_confidence": "high"},
        "reputation_intelligence": {
            "high_confidence_matches": [],
            "other_matches": [],
            "required_sources_available": True,
        },
        "identity_alignment": {
            "status": "aligned",
            "aligned": True,
            "complete": True,
            "http_exit_ip": {"matches": True},
            "webrtc": {"matches": True},
            "timezone": {"matches": True},
            "locale": {"matches": True},
            "dns": {"matches": True},
        },
        "site_outcomes": {
            "cloudflare": {"verdict": "passed"},
            "google": {"verdict": "results"},
        },
        "timestamp_utc": "2026-07-21T00:00:00Z",
    })
    assert summary["reputation"] == "clean_observed"
    assert summary["suitable_for_protected_sites"] == "yes"
    assert summary["type"] == "mobile"
    assert summary["type_confidence"] == "high"
    assert summary["observation_scope"] == {
        "timestamp_utc": "2026-07-21T00:00:00Z",
        "sites": ["cloudflare_turnstile_demo", "google_search"],
    }


@pytest.mark.parametrize(
    ("identity", "sources_available", "expected_reputation"),
    [
        ({"status": "unknown", "aligned": None, "complete": False}, True, "unknown"),
        ({"status": "aligned", "aligned": True, "complete": True}, False, "unknown"),
        ({"status": "mismatch", "aligned": False, "complete": True}, True, "questionable"),
    ],
)
def test_clean_observed_rejects_missing_sources_or_identity(
    identity, sources_available, expected_reputation
):
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "classification": {"type": "unknown", "type_confidence": "low"},
        "reputation_intelligence": {
            "high_confidence_matches": [],
            "other_matches": [],
            "required_sources_available": sources_available,
        },
        "identity_alignment": identity,
        "site_outcomes": {
            "cloudflare": {"verdict": "passed"},
            "google": {"verdict": "results"},
        },
    })

    assert summary["reputation"] == expected_reputation
    assert summary["suitable_for_protected_sites"] == "uncertain"


def test_claimed_alignment_without_required_field_evidence_is_unknown():
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "classification": {"type": "mobile", "type_confidence": "high"},
        "reputation_intelligence": {
            "high_confidence_matches": [],
            "other_matches": [],
            "required_sources_available": True,
        },
        "identity_alignment": {"status": "aligned", "aligned": True, "complete": True},
        "site_outcomes": {
            "cloudflare": {"verdict": "passed"},
            "google": {"verdict": "results"},
        },
    })

    assert summary["reputation"] == "unknown"


def test_cloudflare_explicit_block_is_decisive():
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "classification": {"type": "unknown", "type_confidence": "low"},
        "reputation_intelligence": {
            "high_confidence_matches": [],
            "other_matches": [],
            "required_sources_available": False,
        },
        "identity_alignment": {"status": "unknown", "aligned": None, "complete": False},
        "site_outcomes": {
            "cloudflare": {"verdict": "blocked"},
            "google": {"verdict": "unknown"},
        },
    })

    assert summary["reputation"] == "blocked"
    assert summary["suitable_for_protected_sites"] == "no"


def test_secret_guard_rejects_nested_password():
    with pytest.raises(ValueError, match="secret"):
        assert_no_secrets({"nested": ["sample-password"]}, {"sample-password"})


def test_secret_guard_rejects_secret_embedded_in_a_value():
    with pytest.raises(ValueError, match="secret"):
        assert_no_secrets({"authorization": "Bearer token-123"}, {"token-123"})


def test_proxy_redaction_supports_uri_and_colon_formats():
    assert redact_proxy("socks5://u:p@203.0.113.8:1080") == "socks5://***:***@203.0.113.8:1080"
    assert redact_proxy("203.0.113.8:1080:u:p") == "203.0.113.8:1080:***:***"


@pytest.mark.parametrize(
    ("proxy", "expected"),
    [
        ("socks5://user:p@ss@proxy.example:1080", "socks5://***:***@proxy.example:1080"),
        ("http://user%40name:pass%2Fword@proxy.example:8080", "http://***:***@proxy.example:8080"),
        ("socks5://user:@[2001:db8::8]:1080", "socks5://***:***@[2001:db8::8]:1080"),
        ("https://proxy.example:8443", "https://proxy.example:8443"),
    ],
)
def test_proxy_redaction_reconstructs_only_the_validated_endpoint(proxy, expected):
    assert redact_proxy(proxy) == expected


def test_malformed_credentialed_proxy_is_never_returned_verbatim():
    malformed = "socks5://user:secret@proxy.example:1080/path?query#fragment"

    redacted = redact_proxy(malformed)

    assert "user" not in redacted
    assert "secret" not in redacted
    assert "query" not in redacted
    assert "fragment" not in redacted
