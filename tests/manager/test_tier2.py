from __future__ import annotations

from manager_backend.features.diagnostics.gates import evaluate_release_gates
from manager_backend.features.diagnostics.tier2 import (
    compare_tls,
    tier2_evidence,
    webrtc_ice_verdict,
)


_JA4 = "t13d1516h2_8daaf6152771_d8a2da3f94cd"


def _cand(ip: str, typ: str = "srflx") -> str:
    return f"candidate:1 1 udp 1677729535 {ip} 51234 typ {typ} raddr 0.0.0.0 rport 0"


def test_compare_tls_matches_identical_and_flags_ja4_divergence():
    golden = {"ja4": _JA4, "akamai_h2": "52d84b", "ja3_hash": "abc"}
    assert compare_tls(golden, golden)["match"] is True

    off = {**golden, "ja4": "t13d1516h2_DIFFERENT_d8a2da3f94cd"}
    result = compare_tls(off, golden)
    assert result["match"] is False
    assert any(d["field"] == "ja4" for d in result["divergences"])


def test_compare_tls_ignores_grease_randomized_ja3_hash():
    # Raw JA3 hash is GREASE-randomized per connection, so a difference there is not a
    # divergence — only the GREASE-stable JA4 + HTTP/2 (akamai) fingerprints are compared.
    a = {"ja4": _JA4, "akamai_h2": "A", "ja3_hash": "hash1"}
    b = {"ja4": _JA4, "akamai_h2": "A", "ja3_hash": "hash2"}
    assert compare_tls(a, b)["match"] is True


def test_webrtc_no_leak_when_all_candidates_are_the_proxy_ip():
    cands = [_cand("203.0.113.9", "srflx"), _cand("203.0.113.9", "host")]
    assert webrtc_ice_verdict(cands, allowed_ips=["203.0.113.9"])["leak"] is False


def test_webrtc_leak_when_a_host_ip_is_present():
    result = webrtc_ice_verdict([_cand("192.168.1.5", "host")], allowed_ips=["203.0.113.9"])
    assert result["leak"] is True
    assert "192.168.1.5" in result["leaked_ips"]


def test_webrtc_ignores_mdns_obfuscated_host_candidates():
    result = webrtc_ice_verdict([_cand("a1b2c3d4-1234.local", "host")], allowed_ips=[])
    assert result["leak"] is False


def test_tier2_evidence_feeds_release_gates():
    evidence = tier2_evidence(
        webrtc_result={"leak": True, "leaked_ips": ["192.168.1.5"]},
        tls_result={"match": False, "divergences": [{"field": "ja4"}]},
    )
    result = evaluate_release_gates(evidence)
    assert result["release_ready"] is False
    gates = {item["gate"] for item in result["blocked"]}
    assert {"G3", "G10"} <= gates


def test_tier2_evidence_clean_when_matched_and_no_leak():
    evidence = tier2_evidence(
        webrtc_result={"leak": False, "leaked_ips": []},
        tls_result={"match": True, "divergences": []},
    )
    assert evaluate_release_gates(evidence)["release_ready"] is True
