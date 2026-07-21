"""Offline tests for the proxy-quality orchestrator and CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import traceback
import zlib

import pytest

import benchmarks.proxy_quality as proxy_quality
from benchmarks.proxy_intelligence import ProxyConnectivityError


PROXY = "socks5://scan-user:scan-password@proxy.example:1080"


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _write_test_png(path: Path, *, metadata: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
    ]
    if metadata is not None:
        chunks.append(_png_chunk(b"tEXt", f"Comment\0{metadata}".encode("utf-8")))
    chunks.extend(
        [
            _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")),
            _png_chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))


def _patch_scan_dependencies(monkeypatch, *, high_matches=None, other_matches=None):
    monkeypatch.setattr(
        proxy_quality,
        "resolve_exit_ip",
        lambda _proxy: {
            "success": True,
            "exit_ip": "203.0.113.80",
            "exit_ip_agreement": True,
            "latency_ms": [1.0, 2.0, 3.0],
            "latency_median_ms": 2.0,
            "echo_services": [
                {"source": "ipify", "status": "available", "ip": "203.0.113.80", "latency_ms": 1.0},
                {"source": "aws_checkip", "status": "available", "ip": "203.0.113.80", "latency_ms": 2.0},
                {"source": "ipify", "status": "available", "ip": "203.0.113.80", "latency_ms": 3.0},
            ],
            "country_consistency": "unavailable",
            "headers": {"Proxy-Authorization": "scan-password"},
        },
    )
    monkeypatch.setattr(
        proxy_quality,
        "collect_intelligence",
        lambda _ip, _cache, _token: {
            "signals": [
                {
                    "source": "ipinfo",
                    "ip": "203.0.113.80",
                    "is_mobile": True,
                    "provider_raw_html": "scan-password",
                },
                {"source": "carrier", "mcc": "452"},
            ],
            "high_confidence_matches": list(high_matches or []),
            "other_matches": list(other_matches or []),
            "required_source_status": {
                "ipsum": "available",
                "firehol_level1": "available",
                "firehol_level2": "available",
            },
            "required_sources_available": True,
            "manifest": [
                {
                    "source": "ipinfo",
                    "status": "available",
                    "retrieved_at": "2026-07-21T00:00:00Z",
                    "sha256": "abc123",
                    "matches": [],
                    "repository_url": "https://github.com/ipinfo",
                    "dataset_url": "https://api.ipinfo.io/lite/{ip}",
                    "license_url": "https://ipinfo.io/terms-of-service",
                    "cookies": "scan-password",
                }
            ],
            "sources": [{"raw": "must-not-be-used"}],
        },
    )


def test_scan_writes_safe_timestamped_artifacts_and_removes_profile(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    observed: dict[str, Path] = {}

    def fake_browser_checks(
        proxy: str,
        profile_dir: Path,
        screenshot_dir: Path,
        *,
        expected_exit_ip: str,
    ):
        assert proxy == PROXY
        assert expected_exit_ip == "203.0.113.80"
        assert profile_dir.is_dir()
        observed["profile"] = profile_dir
        observed["screenshots"] = screenshot_dir
        _write_test_png(screenshot_dir / "cloudflare.png", metadata="scan-password")
        _write_test_png(screenshot_dir / "google.png")
        return {
            "identity": {
                "status": "aligned",
                "aligned": True,
                "complete": True,
                "http_exit_ip": {"observed": "203.0.113.80", "matches": True},
                "webrtc": {"observed_ips": ["203.0.113.80"], "matches": True},
                "timezone": {"observed": "Etc/UTC", "matches": True},
                "locale": {"observed": "en-US", "matches": True},
                "dns": {"status": "proxied", "matches": True},
            },
            "cloudflare": {"verdict": "passed", "screenshot_captured": True},
            "google": {"verdict": "results", "screenshot_captured": True},
            "captcha_token": "scan-password",
        }

    monkeypatch.setattr(proxy_quality, "run_browser_checks", fake_browser_checks)

    result = proxy_quality.run_proxy_quality_scan(
        PROXY,
        tmp_path,
        browser_checks=True,
        ipinfo_token="ipinfo-secret",
    )

    artifact_path = Path(result["artifact_path"])
    artifact_dir = artifact_path.parent
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    sources = json.loads((artifact_dir / "sources.json").read_text(encoding="utf-8"))

    assert artifact_path.name == "report.json"
    assert artifact_dir.parent == tmp_path
    assert set(report) == {
        "connectivity",
        "classification",
        "reputation_intelligence",
        "identity_alignment",
        "site_outcomes",
        "summary",
        "proxy",
        "timestamp_utc",
        "sources_manifest",
        "related_checks",
    }
    assert report["proxy"] == "socks5://***:***@proxy.example:1080"
    assert report["connectivity"] == {
        "success": True,
        "exit_ip": "203.0.113.80",
        "exit_ip_agreement": True,
        "latency_ms": [1.0, 2.0, 3.0],
        "latency_median_ms": 2.0,
        "echo_services": [
            {"source": "ipify", "status": "available", "ip": "203.0.113.80", "latency_ms": 1.0},
            {"source": "aws_checkip", "status": "available", "ip": "203.0.113.80", "latency_ms": 2.0},
            {"source": "ipify", "status": "available", "ip": "203.0.113.80", "latency_ms": 3.0},
        ],
        "country_consistency": "unavailable",
    }
    assert report["classification"]["type"] == "mobile"
    assert report["classification"]["type_confidence"] == "high"
    assert report["classification"]["conflicts"] == []
    assert [item["source"] for item in report["classification"]["evidence"]] == [
        "ipinfo",
        "carrier",
    ]
    assert "provider_raw_html" not in json.dumps(report["classification"])
    assert report["identity_alignment"]["status"] == "aligned"
    assert report["site_outcomes"] == {
        "cloudflare": {
            "verdict": "passed",
            "screenshot_captured": True,
            "screenshot": "cloudflare.png",
        },
        "google": {
            "verdict": "results",
            "screenshot_captured": True,
            "screenshot": "google.png",
        },
    }
    assert report["summary"] == {
        "type": "mobile",
        "type_confidence": "high",
        "reputation": "clean_observed",
        "suitable_for_protected_sites": "yes",
        "observation_scope": {
            "timestamp_utc": report["timestamp_utc"],
            "sites": ["cloudflare_turnstile_demo", "google_search"],
        },
    }
    assert report["sources_manifest"] == sources
    assert "cookies" not in sources[0]
    assert "headers" not in report["connectivity"]
    assert observed["screenshots"] == artifact_dir
    assert not observed["profile"].exists()
    assert (artifact_dir / "cloudflare.png").is_file()
    assert b"scan-password" not in (artifact_dir / "cloudflare.png").read_bytes()
    assert report["related_checks"]["pixelscan"]["automatic"] is False
    assert report["related_checks"]["cloudflare_turnstile_demo"]["third_party"] is True
    serialized = artifact_path.read_text(encoding="utf-8") + json.dumps(sources)
    for secret in (PROXY, "scan-user", "scan-password", "ipinfo-secret"):
        assert secret not in serialized


def test_skip_browser_records_skipped_and_unknown(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    monkeypatch.setattr(
        proxy_quality,
        "run_browser_checks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser called")),
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=False, ipinfo_token=None
    )
    report = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert report["site_outcomes"] == {
        "cloudflare": {"verdict": "skipped", "screenshot_captured": False, "screenshot": None},
        "google": {"verdict": "skipped", "screenshot_captured": False, "screenshot": None},
    }
    assert report["identity_alignment"] == {
        "status": "unknown",
        "aligned": None,
        "complete": False,
    }
    assert report["summary"] == {
        "type": "mobile",
        "type_confidence": "high",
        "reputation": "unknown",
        "suitable_for_protected_sites": "uncertain",
    }


def test_skip_browser_still_reports_bad_reputation_as_completed(tmp_path, monkeypatch):
    _patch_scan_dependencies(
        monkeypatch,
        high_matches=[
            {
                "source": "ipsum",
                "network": "203.0.113.0/24",
                "category": "aggregated_abuse",
                "granularity": "cidr",
            }
        ],
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=False, ipinfo_token=None
    )
    report = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert report["summary"] == {
        "type": "mobile",
        "type_confidence": "high",
        "reputation": "blocked",
        "suitable_for_protected_sites": "no",
    }
    assert report["reputation_intelligence"]["high_confidence_matches"][0] == {
        "source": "ipsum",
        "network": "203.0.113.0/24",
        "category": "aggregated_abuse",
        "granularity": "cidr",
    }


def test_skip_browser_other_matches_are_questionable(tmp_path, monkeypatch):
    _patch_scan_dependencies(
        monkeypatch,
        other_matches=[
            {
                "source": "firehol_level2",
                "network": "203.0.113.0/24",
                "category": "broader_blocklist",
                "granularity": "cidr",
            }
        ],
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=False, ipinfo_token=None
    )
    report = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert report["site_outcomes"] == {
        "cloudflare": {"verdict": "skipped", "screenshot_captured": False, "screenshot": None},
        "google": {"verdict": "skipped", "screenshot_captured": False, "screenshot": None},
    }
    assert report["summary"] == {
        "type": "mobile",
        "type_confidence": "high",
        "reputation": "questionable",
        "suitable_for_protected_sites": "uncertain",
    }


def test_unavailable_required_source_prevents_clean_observed(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)

    def unavailable_source(_ip, _cache, _token):
        return {
            "signals": [{"source": "sapics", "asn": 3257, "asn_name": "GTT-BACKBONE GTT"}],
            "high_confidence_matches": [],
            "other_matches": [],
            "required_source_status": {
                "ipsum": "available",
                "firehol_level1": "unavailable",
                "firehol_level2": "available",
            },
            "required_sources_available": False,
            "manifest": [],
        }

    monkeypatch.setattr(proxy_quality, "collect_intelligence", unavailable_source)
    monkeypatch.setattr(
        proxy_quality,
        "run_browser_checks",
        lambda *_args, **_kwargs: {
            "identity": {"status": "aligned", "aligned": True, "complete": True},
            "cloudflare": {"verdict": "passed", "screenshot_captured": False},
            "google": {"verdict": "results", "screenshot_captured": False},
        },
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=True, ipinfo_token=None
    )
    report = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert report["classification"]["type"] == "unknown"
    assert report["classification"]["evidence"][0]["asn"] == 3257
    assert report["reputation_intelligence"]["required_sources_available"] is False
    assert report["summary"]["reputation"] == "unknown"


def test_browser_identity_mismatch_makes_scan_questionable(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    monkeypatch.setattr(
        proxy_quality,
        "run_browser_checks",
        lambda *_args, **_kwargs: {
            "identity": {
                "status": "mismatch",
                "aligned": False,
                "complete": True,
                "http_exit_ip": {"observed": "203.0.113.81", "matches": False},
            },
            "cloudflare": {"verdict": "passed", "screenshot_captured": False},
            "google": {"verdict": "results", "screenshot_captured": False},
        },
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=True, ipinfo_token=None
    )
    report = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert report["identity_alignment"]["status"] == "mismatch"
    assert report["identity_alignment"]["aligned"] is False
    assert report["identity_alignment"]["http_exit_ip"]["observed"] == "203.0.113.81"
    assert report["summary"]["reputation"] == "questionable"


def test_nested_credentials_abort_before_any_final_replace(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)

    def intelligence_with_nested_secret(_ip, _cache, _token):
        return {
            "signals": [],
            "high_confidence_matches": [],
            "other_matches": [],
            "manifest": [
                {
                    "source": "ipinfo",
                    "status": "available",
                    "repository_url": "https://scan-user@example.invalid/source",
                }
            ],
        }

    monkeypatch.setattr(proxy_quality, "collect_intelligence", intelligence_with_nested_secret)
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def recording_replace(self: Path, target: Path):
        replace_calls.append((self, Path(target)))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    with pytest.raises(ValueError, match="secret"):
        proxy_quality.run_proxy_quality_scan(
            PROXY, tmp_path, browser_checks=False, ipinfo_token=None
        )

    assert replace_calls == []
    assert not list(tmp_path.rglob("report.json"))
    assert not list(tmp_path.rglob("sources.json"))


def test_json_artifacts_are_fsynced_and_replaced_from_sibling_tmp_files(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    fsynced: list[int] = []
    replacements: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    monkeypatch.setattr(os, "fsync", lambda descriptor: fsynced.append(descriptor))

    def recording_replace(self: Path, target: Path):
        replacements.append((self, Path(target)))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=False, ipinfo_token=None
    )
    artifact_dir = Path(result["artifact_path"]).parent

    assert len(fsynced) == 2
    assert replacements == [
        (artifact_dir / "sources.json.tmp", artifact_dir / "sources.json"),
        (artifact_dir / "report.json.tmp", artifact_dir / "report.json"),
    ]
    assert not list(artifact_dir.glob("*.tmp"))


def test_unrecognized_browser_text_is_not_serialized_as_a_verdict(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    raw_html = "<html><body>provider response body</body></html>"
    monkeypatch.setattr(
        proxy_quality,
        "run_browser_checks",
        lambda *_args, **_kwargs: {
            "cloudflare": {"verdict": raw_html, "screenshot_captured": False},
            "google": {"verdict": raw_html, "screenshot_captured": False},
        },
    )

    result = proxy_quality.run_proxy_quality_scan(
        PROXY, tmp_path, browser_checks=True, ipinfo_token=None
    )
    report_text = Path(result["artifact_path"]).read_text(encoding="utf-8")
    report = json.loads(report_text)

    assert report["site_outcomes"] == {
        "cloudflare": {"verdict": "error", "screenshot_captured": False, "screenshot": None},
        "google": {"verdict": "unknown", "screenshot_captured": False, "screenshot": None},
    }
    assert raw_html not in report_text


def test_second_replace_failure_removes_partial_final_artifact(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    original_replace = Path.replace

    def fail_report_replace(self: Path, target: Path):
        if self.name == "report.json.tmp":
            raise OSError("disk failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_report_replace)

    with pytest.raises(proxy_quality.ArtifactWriteError):
        proxy_quality.run_proxy_quality_scan(
            PROXY, tmp_path, browser_checks=False, ipinfo_token=None
        )

    artifact_dirs = [path for path in tmp_path.iterdir() if path.is_dir() and path.name != ".cache"]
    assert len(artifact_dirs) == 1
    assert not (artifact_dirs[0] / "sources.json").exists()
    assert not (artifact_dirs[0] / "report.json").exists()
    assert not list(artifact_dirs[0].glob("*.tmp"))


def test_percent_encoded_parsed_credentials_are_guarded(tmp_path, monkeypatch):
    encoded_proxy = "http://user%40name:pass%2Fword@proxy.example:8080"
    _patch_scan_dependencies(monkeypatch)

    def intelligence_with_encoded_username(_ip, _cache, _token):
        return {
            "signals": [],
            "high_confidence_matches": [],
            "other_matches": [],
            "manifest": [
                {
                    "source": "ipinfo",
                    "status": "available",
                    "repository_url": "https://example.invalid/user%40name",
                }
            ],
        }

    monkeypatch.setattr(proxy_quality, "collect_intelligence", intelligence_with_encoded_username)

    with pytest.raises(ValueError, match="secret"):
        proxy_quality.run_proxy_quality_scan(
            encoded_proxy, tmp_path, browser_checks=False, ipinfo_token=None
        )

    assert not list(tmp_path.rglob("report.json"))


def test_png_metadata_is_validated_and_stripped_before_artifact_finalization(tmp_path):
    screenshot = tmp_path / "evidence.png"
    _write_test_png(screenshot, metadata="sample-password")

    proxy_quality._sanitize_png_metadata(screenshot, {"sample-password"})

    payload = screenshot.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"tEXt" not in payload
    assert b"sample-password" not in payload


def test_partial_screenshot_is_removed_when_capture_did_not_complete(tmp_path):
    screenshot = tmp_path / "google.png"
    _write_test_png(screenshot, metadata="sample-password")
    browser_result = {
        "google": {"verdict": "unknown", "screenshot_captured": False},
        "cloudflare": {"verdict": "error", "screenshot_captured": False},
    }

    proxy_quality._sanitize_browser_screenshots(
        tmp_path, browser_result, {"sample-password"}
    )

    assert not screenshot.exists()


def test_rejected_screenshot_is_removed_instead_of_leaving_unsafe_bytes(tmp_path):
    screenshot = tmp_path / "google.png"
    screenshot.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + _png_chunk(b"ABCD", b"sample-password")
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )
    browser_result = {
        "google": {"verdict": "unknown", "screenshot_captured": True},
        "cloudflare": {"verdict": "error", "screenshot_captured": False},
    }

    with pytest.raises(proxy_quality.UnsafeArtifactError):
        proxy_quality._sanitize_browser_screenshots(
            tmp_path, browser_result, {"sample-password"}
        )

    assert not screenshot.exists()


def test_direct_network_control_writes_a_separate_safe_artifact(tmp_path, monkeypatch):
    observed_profile = None

    def fake_control(profile_dir, screenshot_path):
        nonlocal observed_profile
        observed_profile = profile_dir
        assert profile_dir.is_dir()
        _write_test_png(screenshot_path, metadata="nonessential control metadata")
        return {"verdict": "results", "screenshot_captured": True}

    monkeypatch.setattr(proxy_quality, "run_direct_google_control", fake_control)

    result = proxy_quality.run_direct_network_control(tmp_path)
    artifact = Path(result["artifact_path"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert artifact.name == "direct-control.json"
    assert artifact.parent.parent == tmp_path / "direct-control"
    assert payload["control"] == "direct_network_google"
    assert payload["google"] == {
        "verdict": "results",
        "screenshot_captured": True,
        "screenshot": "google.png",
    }
    assert payload["excluded_from_proxy_report"] is True
    assert "scan-user" not in json.dumps(payload)
    assert "scan-password" not in json.dumps(payload)
    assert (artifact.parent / "google.png").is_file()
    assert b"tEXt" not in (artifact.parent / "google.png").read_bytes()
    assert observed_profile is not None and not observed_profile.exists()


def test_artifact_exception_traceback_scrubs_credential_bearing_path(tmp_path, monkeypatch):
    _patch_scan_dependencies(monkeypatch)
    blocked_output = tmp_path / "scan-password"
    blocked_output.write_text("not a directory", encoding="utf-8")

    with pytest.raises(proxy_quality.ArtifactWriteError) as exc_info:
        proxy_quality.run_proxy_quality_scan(
            PROXY, blocked_output, browser_checks=False, ipinfo_token=None
        )

    rendered = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert "scan-password" not in rendered


def _clear_cli_environment(monkeypatch):
    for name in ("CLOAK_TEST_PROXY", "IPINFO_TOKEN", "PROXY_QUALITY_SKIP_BROWSER"):
        monkeypatch.delenv(name, raising=False)


def test_cli_missing_proxy_exits_2_without_environment_contents(monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-print-this")

    assert proxy_quality.main([]) == 2
    captured = capsys.readouterr()
    assert "do-not-print-this" not in captured.out + captured.err


def test_cli_rejects_proxy_arguments_without_echoing_them(monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    argument = "socks5://argument-user:argument-password@proxy.example:1080"

    assert proxy_quality.main([argument]) == 2
    captured = capsys.readouterr()
    assert "argument-user" not in captured.out + captured.err
    assert "argument-password" not in captured.out + captured.err

    assert proxy_quality.main(["--output-dir", argument]) == 2
    captured = capsys.readouterr()
    assert "argument-user" not in captured.out + captured.err
    assert "argument-password" not in captured.out + captured.err


def test_cli_accepts_only_a_safe_output_directory_option(tmp_path, monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    selected = tmp_path / "custom-output"
    calls = []

    def completed_scan(proxy, output_dir, *, browser_checks, ipinfo_token):
        calls.append((proxy, output_dir, browser_checks, ipinfo_token))
        return {
            "proxy": "socks5://***:***@proxy.example:1080",
            "summary": {
                "type": "unknown",
                "type_confidence": "low",
                "reputation": "unknown",
                "suitable_for_protected_sites": "uncertain",
            },
            "artifact_path": str(selected / "timestamp" / "report.json"),
        }

    monkeypatch.setattr(proxy_quality, "run_proxy_quality_scan", completed_scan)

    assert proxy_quality.main(["--output-dir", str(selected)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert calls == [(PROXY, selected, True, None)]


def test_cli_direct_control_is_separate_and_does_not_read_proxy_input(
    tmp_path, monkeypatch, capsys
):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    selected = tmp_path / "direct-control"
    calls = []

    def completed_control(output_dir):
        calls.append(output_dir)
        return {
            "control": "direct_network_google",
            "google": {"verdict": "results", "screenshot_captured": True},
            "artifact_path": str(selected / "timestamp" / "direct-control.json"),
        }

    monkeypatch.setattr(proxy_quality, "run_direct_network_control", completed_control)

    assert proxy_quality.main(
        ["--direct-control", "--output-dir", str(selected)]
    ) == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert captured.err == ""
    assert output["control"] == "direct_network_google"
    assert "proxy" not in output
    assert "scan-user" not in captured.out
    assert "scan-password" not in captured.out
    assert calls == [selected]


@pytest.mark.parametrize("arguments", [["--output-dir"], ["--unknown"], ["--output-dir", "one", "two"]])
def test_cli_rejects_malformed_or_unknown_options_without_echoing_values(
    arguments, monkeypatch, capsys
):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)

    assert proxy_quality.main(arguments) == 2
    captured = capsys.readouterr()
    assert "scan-user" not in captured.out + captured.err
    assert "scan-password" not in captured.out + captured.err


def test_cli_connectivity_failure_exits_3_and_scrubs_exception(monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    monkeypatch.setattr(
        proxy_quality,
        "run_proxy_quality_scan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProxyConnectivityError("scan-password leaked by transport")
        ),
    )

    assert proxy_quality.main([]) == 3
    captured = capsys.readouterr()
    assert "scan-password" not in captured.out + captured.err


def test_cli_artifact_failure_exits_4_and_scrubs_exception(monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    monkeypatch.setattr(
        proxy_quality,
        "run_proxy_quality_scan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            proxy_quality.ArtifactWriteError("scan-password in output path")
        ),
    )

    assert proxy_quality.main([]) == 4
    captured = capsys.readouterr()
    assert "scan-password" not in captured.out + captured.err


def test_cli_browser_artifact_oserror_exits_4_through_orchestrator(
    tmp_path, monkeypatch, capsys
):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    monkeypatch.setattr(proxy_quality, "_DEFAULT_OUTPUT_DIR", tmp_path)
    _patch_scan_dependencies(monkeypatch)
    monkeypatch.setattr(
        proxy_quality,
        "run_browser_checks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("screenshot path contains scan-password")
        ),
    )

    assert proxy_quality.main([]) == 4
    captured = capsys.readouterr()
    assert "scan-password" not in captured.out + captured.err
    assert "artifact" in captured.err.lower()
    assert not list(tmp_path.rglob("report.json"))


def test_cli_bad_reputation_exits_0_and_prints_only_safe_payload(monkeypatch, capsys, tmp_path):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    monkeypatch.setenv("PROXY_QUALITY_SKIP_BROWSER", "1")
    artifact = tmp_path / "20260721T000000Z" / "report.json"
    calls = []

    def completed_scan(proxy, output_dir, *, browser_checks, ipinfo_token):
        calls.append((proxy, output_dir, browser_checks, ipinfo_token))
        return {
            "proxy": "socks5://***:***@proxy.example:1080",
            "summary": {
                "type": "mobile",
                "type_confidence": "high",
                "reputation": "blocked",
                "suitable_for_protected_sites": "no",
            },
            "artifact_path": str(artifact),
        }

    monkeypatch.setattr(proxy_quality, "run_proxy_quality_scan", completed_scan)

    assert proxy_quality.main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "proxy": "socks5://***:***@proxy.example:1080",
        "summary": {
            "type": "mobile",
            "type_confidence": "high",
            "reputation": "blocked",
            "suitable_for_protected_sites": "no",
        },
        "artifact_path": str(artifact),
    }
    assert calls[0][0] == PROXY
    assert calls[0][2] is False


def test_cli_invalid_skip_setting_and_unexpected_errors_are_scrubbed(monkeypatch, capsys):
    _clear_cli_environment(monkeypatch)
    monkeypatch.setenv("CLOAK_TEST_PROXY", PROXY)
    monkeypatch.setenv("PROXY_QUALITY_SKIP_BROWSER", "sometimes")

    assert proxy_quality.main([]) == 2
    first = capsys.readouterr()
    assert "scan-password" not in first.out + first.err

    monkeypatch.setenv("PROXY_QUALITY_SKIP_BROWSER", "0")
    monkeypatch.setattr(
        proxy_quality,
        "run_proxy_quality_scan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("unexpected scan-password")
        ),
    )

    assert proxy_quality.main([]) == 1
    second = capsys.readouterr()
    assert "scan-password" not in second.out + second.err
