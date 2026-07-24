from __future__ import annotations

from manager_backend.features.diagnostics.gates import (
    BLOCKING_GATES,
    TELEMETRY_KEYS,
    evaluate_release_gates,
    evidence_from_probe,
)
from manager_backend.features.diagnostics.probe import normalize_probe


def test_clean_evidence_is_release_ready():
    result = evaluate_release_gates({})
    assert result["release_ready"] is True
    assert result["blocked"] == []


def test_a_true_blocker_blocks_the_release():
    result = evaluate_release_gates({"direct_host_ip_leak": True})
    assert result["release_ready"] is False
    assert any(item["gate"] == "G1" for item in result["blocked"])


def test_all_eleven_gates_are_representable():
    assert len(BLOCKING_GATES) == 11
    # Every gate keys off a distinct evidence flag.
    conditions = {key for key, _title in BLOCKING_GATES.values()}
    assert len(conditions) == 11


def test_telemetry_is_recorded_but_never_blocks():
    evidence = {"captcha_occurrence": 7, "uniqueness_score": 0.42, "checker_timeout": True}
    result = evaluate_release_gates(evidence)
    assert result["release_ready"] is True  # telemetry never blocks
    assert result["telemetry"]["captcha_occurrence"] == 7
    assert set(result["telemetry"]) <= set(TELEMETRY_KEYS)


def test_evidence_from_probe_maps_contradictions_to_gates():
    contradictory = normalize_probe(
        {
            "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/146",
            "platform": "MacIntel",
            "userAgentData": {"platform": "macOS"},
            "window": {"outerWidth": 2560, "outerHeight": 1440},
            "screen": {"width": 1920, "height": 1080},
            "webdriver": True,
            "nativeIntegrity": {"hardwareConcurrencyGetter": "function() { return 8; }"},
        }
    )
    evidence = evidence_from_probe(contradictory)
    result = evaluate_release_gates(evidence)
    assert result["release_ready"] is False
    blocked_gates = {item["gate"] for item in result["blocked"]}
    assert {"G5", "G8", "G9"} <= blocked_gates
