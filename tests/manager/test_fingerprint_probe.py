from __future__ import annotations

import json
from contextlib import contextmanager

from manager_backend.features.diagnostics.probe import (
    PROBE_SCHEMA_VERSION,
    live_probe_enabled,
    normalize_probe,
    probe_status_and_findings,
    run_live_probe,
    run_probe,
)


def _windows_raw(**overrides) -> dict:
    raw = {
        "userAgent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        "platform": "Win32",
        "userAgentData": {"platform": "Windows", "mobile": False},
        "languages": ["en-US", "en"],
        "hardwareConcurrency": 8,
        "deviceMemory": 8,
        "webdriver": False,
        "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
        "window": {"outerWidth": 1920, "outerHeight": 1080, "innerWidth": 1920, "innerHeight": 947},
        "intl": {"timeZone": "America/New_York", "locale": "en-US"},
        "canvas": "abc123",
        "webgl": {"vendor": "Google Inc.", "renderer": "ANGLE (Intel)"},
        "audio": "124.04",
        "nativeIntegrity": {
            "hardwareConcurrencyGetter": "function get hardwareConcurrency() { [native code] }",
        },
    }
    raw.update(overrides)
    return raw


def test_normalize_wraps_raw_and_verdict_separately_with_schema_version():
    result = normalize_probe(_windows_raw(), host_username="alice")
    assert result["probe_schema_version"] == PROBE_SCHEMA_VERSION
    assert set(result) == {"probe_schema_version", "raw", "verdict"}
    # Raw observation and computed verdict are never conflated.
    assert "userAgent" in result["raw"]
    assert "userAgent" not in result["verdict"]


def test_coherent_windows_profile_passes_all_verdicts():
    verdict = normalize_probe(_windows_raw(), host_username="alice")["verdict"]
    assert verdict["ua_platform"] == "coherent"
    assert verdict["window_within_screen"] == "coherent"
    assert verdict["automation"] == "clean"


def test_cross_os_user_agent_is_flagged_contradictory():
    raw = _windows_raw(
        userAgent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/146.0.0.0",
        userAgentData={"platform": "macOS", "mobile": False},
        platform="MacIntel",
    )
    assert normalize_probe(raw)["verdict"]["ua_platform"] == "contradictory"


def test_window_larger_than_screen_is_flagged_contradictory():
    raw = _windows_raw(
        window={"outerWidth": 2560, "outerHeight": 1440, "innerWidth": 2560, "innerHeight": 1400}
    )
    assert normalize_probe(raw)["verdict"]["window_within_screen"] == "contradictory"


def test_webdriver_true_flags_automation():
    raw = _windows_raw(webdriver=True)
    assert normalize_probe(raw)["verdict"]["automation"] == "detected"


def test_native_integrity_verdict():
    intact = _windows_raw()  # getter reports [native code]
    assert normalize_probe(intact)["verdict"]["native_integrity"] == "intact"

    tampered = _windows_raw(
        nativeIntegrity={"hardwareConcurrencyGetter": "function get() { return 8; }"}
    )
    assert normalize_probe(tampered)["verdict"]["native_integrity"] == "tampered"

    unknown = _windows_raw(nativeIntegrity={})
    assert normalize_probe(unknown)["verdict"]["native_integrity"] == "unknown"


def test_redacts_machine_username_and_local_paths():
    raw = _windows_raw(
        downloadPath=r"C:\Users\alice\Downloads\report.json",
        note="collected for alice on this host",
    )
    result = normalize_probe(raw, host_username="alice")
    blob = json.dumps(result)
    assert "alice" not in blob
    assert r"C:\Users" not in blob


def test_run_probe_uses_injected_evaluator():
    captured = {}

    def fake_evaluate(script: str) -> dict:
        captured["script"] = script
        return _windows_raw()

    result = run_probe(fake_evaluate, host_username="alice")
    assert "getRandomValues" not in captured["script"]  # collector is a real script
    assert "navigator" in captured["script"]
    assert result["probe_schema_version"] == PROBE_SCHEMA_VERSION
    assert result["verdict"]["ua_platform"] == "coherent"


def test_probe_status_passed_when_coherent():
    status, findings = probe_status_and_findings(normalize_probe(_windows_raw()))
    assert status == "passed"
    assert findings["ua_platform"] == "coherent"


def test_probe_status_failed_on_contradiction():
    raw = _windows_raw(
        window={"outerWidth": 2560, "outerHeight": 1440, "innerWidth": 2560, "innerHeight": 1400}
    )
    status, _findings = probe_status_and_findings(normalize_probe(raw))
    assert status == "failed"


def test_probe_status_warning_on_automation_or_tamper():
    status, _findings = probe_status_and_findings(normalize_probe(_windows_raw(webdriver=True)))
    assert status == "warning"


def test_live_probe_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CLOAK_LIVE_DIAGNOSTICS", raising=False)
    assert live_probe_enabled() is False
    monkeypatch.setenv("CLOAK_LIVE_DIAGNOSTICS", "1")
    assert live_probe_enabled() is True


def test_run_live_probe_orchestrates_open_evaluate_normalize():
    opened = {}

    @contextmanager
    def fake_open_probe_page(snapshot):
        opened["snapshot"] = snapshot
        yield lambda _script: _windows_raw()

    result = run_live_probe(
        {"id": "p1"}, open_probe_page=fake_open_probe_page, host_username="alice"
    )
    assert opened["snapshot"]["id"] == "p1"
    assert result["status"] == "passed"
    assert result["findings"]["automation"] == "clean"
    assert result["probe"]["probe_schema_version"] == PROBE_SCHEMA_VERSION
