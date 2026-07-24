"""Release-gate evaluation (Phase 6 core, doc 08).

Pure logic: given an evidence dict (each hard-blocker key is True when the bad
condition was observed), decide whether the release is blocked, and pass telemetry
through separately. The *collection* of evidence — live leak checks, differential
runs, separation suites — needs the binary; this evaluator is deterministically
testable and is what a CI/harness feeds real evidence into. Telemetry never blocks.
"""

from __future__ import annotations


# Gate id -> (evidence flag, human title). A gate blocks the release when its flag
# is exactly True. Mirrors docs/research/fingerprint-assurance/08-release-gates.md.
BLOCKING_GATES: dict[str, tuple[str, str]] = {
    "G1": ("direct_host_ip_leak", "Direct host-IP leak"),
    "G2": ("dns_or_ipv6_leak", "DNS/IPv6 leak"),
    "G3": ("webrtc_public_ip_contradiction", "WebRTC public-IP contradiction"),
    "G4": ("silent_proxy_fallback", "Silent proxy fallback"),
    "G5": ("ua_kernel_ch_mismatch", "UA/kernel/Client-Hint mismatch"),
    "G6": ("unstable_profile_seed", "Unstable profile seed"),
    "G7": ("profile_storage_crossover", "Profile storage crossover"),
    "G8": ("impossible_device_model", "Impossible device model"),
    "G9": ("new_automation_marker", "New automation marker"),
    "G10": ("structural_divergence_from_chrome", "Structural divergence from genuine Chrome"),
    "G11": ("unsupported_setting_reported_active", "Unsupported setting reported active"),
}

# Recorded and trended, never a build failure.
TELEMETRY_KEYS = (
    "uniqueness_score",
    "captcha_occurrence",
    "proxy_asn_reputation",
    "single_checker_verdict_drift",
    "common_canvas_webgl_hashes",
    "checker_timeout",
)


def evaluate_release_gates(evidence: dict) -> dict:
    blocked = [
        {"gate": gate_id, "condition": condition, "title": title}
        for gate_id, (condition, title) in BLOCKING_GATES.items()
        if evidence.get(condition) is True
    ]
    telemetry = {key: evidence[key] for key in TELEMETRY_KEYS if key in evidence}
    return {"release_ready": not blocked, "blocked": blocked, "telemetry": telemetry}


def evidence_from_probe(normalized_probe: dict) -> dict:
    """Derive the gate evidence a single first-party probe can supply (G5/G8/G9).
    Other gates (G1-G4 network leaks, G6 stability, G7 isolation, G10 differential,
    G11 capability read-back) come from their own live collectors."""
    verdict = normalized_probe["verdict"]
    return {
        "ua_kernel_ch_mismatch": verdict["ua_platform"] == "contradictory",
        "impossible_device_model": verdict["window_within_screen"] == "contradictory",
        "new_automation_marker": (
            verdict["automation"] == "detected" or verdict["native_integrity"] == "tampered"
        ),
    }
