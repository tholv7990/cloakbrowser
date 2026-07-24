"""Tier-2 differential harness (doc 04 "Where JavaScript is NOT enough").

The verdict/comparison logic here is pure and fully tested. The *capture* layer needs
infrastructure this repo cannot provide — a real remote SOCKS5 proxy (to make the F-003
WebRTC UDP-origin question meaningful) and a genuine-Chrome golden captured the same way
(for an authoritative TLS/HTTP-2 comparison). Those functions are marked NEEDS INFRA and
take an injected page opener so the pure logic stays deterministically testable.

Flow in a binary+proxy environment:
  golden      = capture_tls(open_probe_page, chrome_snapshot)     # genuine Chrome
  observed    = capture_tls(open_probe_page, cloak_snapshot)      # CloakBrowser, same proxy
  candidates  = capture_webrtc_candidates(open_probe_page, cloak_snapshot)
  evidence    = tier2_evidence(compare_tls(observed, golden),
                               webrtc_ice_verdict(candidates, allowed_ips=[proxy_exit_ip]))
  gates       = evaluate_release_gates(evidence)   # feeds G3 (WebRTC) and G10 (TLS)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


TLS_ECHO_DEFAULT = "https://tls.peet.ws/api/all"

# GREASE-stable fingerprints only: the raw JA3 hash is randomized per connection, so it
# is captured for the record but never compared.
_COMPARED_TLS_FIELDS = ("ja4", "akamai_h2")


def compare_tls(observed: dict, golden: dict) -> dict:
    """Compare a browser's TLS/HTTP-2 fingerprint to a genuine-Chrome golden. Diverges
    only on the GREASE-stable JA4 / HTTP-2 (akamai) fingerprints."""
    divergences = [
        {"field": field, "observed": observed.get(field), "golden": golden.get(field)}
        for field in _COMPARED_TLS_FIELDS
        if observed.get(field) != golden.get(field)
    ]
    return {"match": not divergences, "divergences": divergences}


def webrtc_ice_verdict(candidates: list[str], *, allowed_ips: list[str]) -> dict:
    """Given the ICE candidates and the IPs allowed to appear (the proxy exit IP), flag
    any other IP as a host leak. mDNS-obfuscated (`*.local`) host candidates are not a
    leak. Definitive proof that UDP *routes* through the proxy still needs a packet
    observer — this checks the reported candidates."""
    allowed = set(allowed_ips)
    leaked = []
    for candidate in candidates:
        parts = candidate.split()
        if len(parts) < 5:
            continue
        ip = parts[4]
        if ip.endswith(".local"):  # mDNS-obfuscated host candidate
            continue
        if ip not in allowed:
            leaked.append(ip)
    return {"leak": bool(leaked), "leaked_ips": sorted(set(leaked))}


def tier2_evidence(
    *, tls_result: dict | None = None, webrtc_result: dict | None = None
) -> dict:
    """Map Tier-2 results to release-gate evidence: WebRTC leak -> G3, TLS divergence
    from genuine Chrome -> G10."""
    evidence: dict[str, bool] = {}
    if webrtc_result is not None:
        evidence["webrtc_public_ip_contradiction"] = bool(webrtc_result.get("leak"))
    if tls_result is not None:
        evidence["structural_divergence_from_chrome"] = not tls_result.get("match", True)
    return evidence


# --- Capture layer (NEEDS INFRA — not exercised by unit tests) ----------------------

# Gathers ICE candidates against a public STUN. Async: candidates arrive over time.
WEBRTC_JS = r"""(async () => {
  try {
    const pc = new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
    const candidates = [];
    pc.onicecandidate = e => { if (e.candidate) candidates.push(e.candidate.candidate); };
    pc.createDataChannel('probe');
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 5000);
      pc.onicegatheringstatechange = () => {
        if (pc.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); }
      };
    });
    pc.close();
    return candidates;
  } catch (e) { return []; }
})()"""


def capture_tls(
    open_probe_page: Callable[[dict], Any],
    snapshot: dict,
    *,
    echo_url: str = TLS_ECHO_DEFAULT,
) -> dict:
    """NEEDS INFRA: navigate to a TLS echo and read the JA4 / JA3 / HTTP-2 fingerprint.
    For a meaningful comparison, run this through the profile's real proxy and capture the
    genuine-Chrome golden identically. `open_probe_page` is injected (live:
    `probe.default_probe_page`; tests: a stub)."""
    # "load" so the full echo response body is present before we read it.
    page_snapshot = {**snapshot, "probe_url": echo_url, "probe_wait_until": "load"}
    with open_probe_page(page_snapshot) as evaluate:
        body = evaluate("document.body.innerText")
    data = json.loads(body) if isinstance(body, str) else body
    tls = data.get("tls") or {}
    http2 = data.get("http2") or {}
    return {
        "ja4": tls.get("ja4"),
        "akamai_h2": http2.get("akamai_fingerprint_hash"),
        "ja3_hash": tls.get("ja3_hash"),
    }


def capture_webrtc_candidates(
    open_probe_page: Callable[[dict], Any],
    snapshot: dict,
    *,
    page_url: str = "https://example.com/",
) -> list[str]:
    """NEEDS INFRA: enumerate ICE candidates over the profile's launch (ideally through a
    real proxy). Returns the raw candidate strings for `webrtc_ice_verdict`."""
    with open_probe_page({**snapshot, "probe_url": page_url}) as evaluate:
        return evaluate(WEBRTC_JS)
