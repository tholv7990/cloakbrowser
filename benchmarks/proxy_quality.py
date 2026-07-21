"""Credential-safe orchestration and CLI for the proxy-quality benchmark."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import zlib

from benchmarks.proxy_intelligence import (
    DatasetCache,
    ProxyConnectivityError,
    collect_intelligence,
    resolve_exit_ip,
    validate_proxy_url,
)
from benchmarks.proxy_quality_models import (
    assert_no_secrets,
    classify_network,
    redact_proxy,
    summarize_report,
)
from benchmarks.proxy_site_checks import run_browser_checks, run_direct_google_control


_DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "results" / "proxy-quality"
_CACHE_MAX_AGE = timedelta(hours=24)
_COLON_PROXY = re.compile(
    r"^(?P<host>.+):(?P<port>\d+):(?P<username>[^:]*):(?P<password>.*)$"
)
_MANIFEST_SCALAR_FIELDS = (
    "source",
    "status",
    "retrieved_at",
    "sha256",
    "repository_url",
    "dataset_url",
    "license_url",
    "version",
    "asset",
)
_SITE_VERDICTS = {
    "cloudflare": frozenset({"passed", "interactive", "blocked", "error", "pending", "unknown", "skipped"}),
    "google": frozenset({"passed", "results", "captcha", "blocked", "consent", "error", "unknown", "skipped"}),
}
_REQUIRED_REPUTATION_SOURCES = ("ipsum", "firehol_level1", "firehol_level2")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_SAFE_ANCILLARY_CHUNKS = frozenset({b"cHRM", b"gAMA", b"sRGB", b"pHYs", b"tRNS", b"bKGD"})
_PIXELSCAN_URL = "https://pixelscan.net/"


class ArtifactWriteError(RuntimeError):
    """Raised when safe benchmark artifacts cannot be completed."""


class UnsafeArtifactError(ArtifactWriteError, ValueError):
    """Raised when a report or console payload contains a known secret."""


def _timestamp_utc(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp_directory_name(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _make_artifact_directory(output_dir: Path, now: datetime) -> Path:
    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        base_name = _timestamp_directory_name(now)
        for suffix in range(1_000):
            name = base_name if suffix == 0 else f"{base_name}-{suffix}"
            candidate = root / name
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            return candidate
    except OSError:
        raise ArtifactWriteError("Unable to create the artifact directory") from None
    raise ArtifactWriteError("Unable to allocate a unique artifact directory")


def _build_secret_set(proxy: str, ipinfo_token: str | None) -> set[str]:
    """Collect authentication material without retaining it in report fields."""

    secrets: set[str] = set()
    parsed = urlsplit(proxy)
    encoded_username = parsed.username
    encoded_password = parsed.password
    if encoded_username is None and encoded_password is None:
        colon_match = _COLON_PROXY.match(proxy)
        if colon_match:
            encoded_username = colon_match.group("username")
            encoded_password = colon_match.group("password")

    username = unquote(encoded_username) if encoded_username is not None else None
    password = unquote(encoded_password) if encoded_password is not None else None

    # An uncredentialed endpoint is public report data, not authentication
    # material.  Credential-bearing raw proxy strings are always guarded.
    if encoded_username is not None or encoded_password is not None:
        secrets.add(proxy)
    secrets.update(
        value
        for value in (
            encoded_username,
            encoded_password,
            username,
            password,
            ipinfo_token,
        )
        if value
    )
    return secrets


def _safe_connectivity(value: object) -> dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    latency = source.get("latency_ms")
    safe_latency = (
        [item for item in latency if isinstance(item, (int, float)) and not isinstance(item, bool)]
        if isinstance(latency, Sequence) and not isinstance(latency, (str, bytes, bytearray))
        else []
    )
    result: dict[str, object] = {
        "success": source.get("success") is True,
        "exit_ip_agreement": source.get("exit_ip_agreement") is True,
        "latency_ms": safe_latency,
    }
    median_latency = source.get("latency_median_ms")
    if isinstance(median_latency, (int, float)) and not isinstance(median_latency, bool):
        result["latency_median_ms"] = median_latency
    observations = source.get("echo_services")
    safe_observations: list[dict[str, object]] = []
    if isinstance(observations, Sequence) and not isinstance(observations, (str, bytes, bytearray)):
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            source_name = observation.get("source")
            status = observation.get("status")
            observed_ip = observation.get("ip")
            observed_latency = observation.get("latency_ms")
            if source_name in {"ipify", "aws_checkip"} and status == "unavailable":
                safe_observations.append({"source": source_name, "status": "unavailable"})
                continue
            if (
                source_name in {"ipify", "aws_checkip"}
                and status == "available"
                and isinstance(observed_ip, str)
                and isinstance(observed_latency, (int, float))
                and not isinstance(observed_latency, bool)
            ):
                try:
                    canonical_ip = str(ipaddress.ip_address(observed_ip))
                except ValueError:
                    continue
                safe_observations.append(
                    {
                        "source": source_name,
                        "status": "available",
                        "ip": canonical_ip,
                        "latency_ms": observed_latency,
                    }
                )
    result["echo_services"] = safe_observations
    country_consistency = source.get("country_consistency")
    result["country_consistency"] = country_consistency if (
        isinstance(country_consistency, bool) or country_consistency == "unavailable"
    ) else "unavailable"
    if isinstance(source.get("exit_ip"), str):
        result["exit_ip"] = source["exit_ip"]
    return result


def _safe_matches(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    matches: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        network = item.get("network")
        category = item.get("category")
        granularity = item.get("granularity")
        if (
            isinstance(source, str)
            and isinstance(network, str)
            and isinstance(category, str)
            and granularity in {"exact_ip", "cidr"}
        ):
            matches.append(
                {
                    "source": source,
                    "network": network,
                    "category": category,
                    "granularity": granularity,
                }
            )
    return matches


def _safe_manifest(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    manifest: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, object] = {}
        for field in _MANIFEST_SCALAR_FIELDS:
            field_value = item.get(field)
            if field_value is None or isinstance(field_value, (str, int, float, bool)):
                entry[field] = field_value
        matches = item.get("matches")
        entry["matches"] = (
            [match for match in matches if isinstance(match, str)]
            if isinstance(matches, Sequence) and not isinstance(matches, (str, bytes, bytearray))
            else []
        )
        manifest.append(entry)
    return manifest


def _signals(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _safe_identity(value: object) -> dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    status = source.get("status")
    if status not in {"aligned", "mismatch", "unknown"}:
        status = "unknown"
    aligned = source.get("aligned") if source.get("aligned") in {True, False, None} else None
    result: dict[str, object] = {
        "status": status,
        "aligned": aligned,
        "complete": source.get("complete") is True,
    }
    field_specs = {
        "http_exit_ip": ("source", "expected", "observed", "matches"),
        "webrtc": (
            "source",
            "expected",
            "observed_ips",
            "mdns_candidate_observed",
            "matches",
        ),
        "timezone": ("source", "expected", "observed", "matches"),
        "locale": ("source", "expected", "observed", "matches"),
        "dns": ("source", "status", "matches"),
    }
    for field, allowed in field_specs.items():
        raw_field = source.get(field)
        if not isinstance(raw_field, Mapping):
            continue
        safe_field: dict[str, object] = {}
        for key in allowed:
            field_value = raw_field.get(key)
            if key == "observed_ips":
                if isinstance(field_value, Sequence) and not isinstance(
                    field_value, (str, bytes, bytearray)
                ):
                    canonical_ips: list[str] = []
                    for candidate in field_value:
                        try:
                            canonical_ips.append(str(ipaddress.ip_address(candidate)))
                        except (TypeError, ValueError):
                            continue
                    safe_field[key] = sorted(set(canonical_ips))
            elif field_value is None or isinstance(field_value, (str, bool)):
                safe_field[key] = field_value
        result[field] = safe_field
    return result


def _site_outcomes(value: object) -> dict[str, dict[str, object]]:
    source = value if isinstance(value, Mapping) else {}
    defaults = {"cloudflare": "error", "google": "unknown"}
    outcomes: dict[str, dict[str, object]] = {}
    for site, default in defaults.items():
        site_result = source.get(site)
        verdict = site_result.get("verdict") if isinstance(site_result, Mapping) else None
        captured = (
            site_result.get("screenshot_captured") is True
            if isinstance(site_result, Mapping)
            else False
        )
        outcomes[site] = {
            "verdict": verdict if verdict in _SITE_VERDICTS[site] else default,
            "screenshot_captured": captured,
            "screenshot": f"{site}.png" if captured else None,
        }
    return outcomes


def _safe_required_source_status(value: object) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    return {
        name: source.get(name) if source.get(name) in {"available", "unavailable"} else "unavailable"
        for name in _REQUIRED_REPUTATION_SOURCES
    }


def _assert_payloads_safe(
    report: dict[str, object], console_payload: dict[str, object], secrets: set[str]
) -> None:
    try:
        assert_no_secrets(report, secrets)
        assert_no_secrets(console_payload, secrets)
    except ValueError:
        raise UnsafeArtifactError("Unsafe secret content was rejected") from None


def _stage_json(path: Path, payload: object) -> Path:
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return temporary


def _sanitize_png_metadata(path: Path, secrets: set[str]) -> None:
    """Validate a PNG and atomically remove nonessential ancillary metadata."""

    try:
        payload = Path(path).read_bytes()
        if not payload.startswith(_PNG_SIGNATURE):
            raise ValueError
        offset = len(_PNG_SIGNATURE)
        chunks: list[bytes] = []
        seen_ihdr = False
        seen_iend = False
        while offset < len(payload):
            if offset + 12 > len(payload):
                raise ValueError
            length = struct.unpack(">I", payload[offset : offset + 4])[0]
            end = offset + 12 + length
            if end > len(payload):
                raise ValueError
            kind = payload[offset + 4 : offset + 8]
            data = payload[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
            if zlib.crc32(kind + data) & 0xFFFFFFFF != expected_crc:
                raise ValueError
            if not seen_ihdr:
                if kind != b"IHDR" or length != 13:
                    raise ValueError
                seen_ihdr = True
            if seen_iend:
                raise ValueError
            is_critical = bool(kind) and 65 <= kind[0] <= 90
            if is_critical or kind in _PNG_SAFE_ANCILLARY_CHUNKS:
                chunks.append(payload[offset:end])
            if kind == b"IEND":
                if length != 0:
                    raise ValueError
                seen_iend = True
            offset = end
        if not seen_ihdr or not seen_iend or offset != len(payload):
            raise ValueError
        sanitized = _PNG_SIGNATURE + b"".join(chunks)
        for secret in (secret for secret in secrets if secret):
            if secret.encode("utf-8", errors="ignore") in sanitized:
                raise UnsafeArtifactError("Unsafe screenshot content was rejected")
        temporary = Path(path).with_name(f"{Path(path).name}.sanitized.tmp")
        with temporary.open("wb") as stream:
            stream.write(sanitized)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except UnsafeArtifactError:
        raise
    except (OSError, ValueError, struct.error):
        raise ArtifactWriteError("Unable to validate browser screenshot") from None


def _sanitize_browser_screenshots(
    artifact_dir: Path, browser_result: object, secrets: set[str]
) -> None:
    if not isinstance(browser_result, Mapping):
        return
    for site in ("cloudflare", "google"):
        site_result = browser_result.get(site)
        screenshot = artifact_dir / f"{site}.png"
        if not isinstance(site_result, dict) or site_result.get("screenshot_captured") is not True:
            try:
                screenshot.unlink(missing_ok=True)
            except OSError:
                raise ArtifactWriteError("Unable to remove incomplete browser screenshot") from None
            continue
        if not screenshot.is_file():
            site_result["screenshot_captured"] = False
            continue
        try:
            _sanitize_png_metadata(screenshot, secrets)
        except ArtifactWriteError:
            try:
                screenshot.unlink(missing_ok=True)
            except OSError:
                raise ArtifactWriteError(
                    "Unable to remove rejected browser screenshot"
                ) from None
            raise


def _write_artifacts(
    report_path: Path, report: dict[str, object], sources_manifest: list[dict[str, object]]
) -> None:
    sources_path = report_path.with_name("sources.json")
    staged: list[Path] = []
    finalized: list[Path] = []
    try:
        staged.append(_stage_json(sources_path, sources_manifest))
        staged.append(_stage_json(report_path, report))
        staged[0].replace(sources_path)
        finalized.append(sources_path)
        staged[1].replace(report_path)
        finalized.append(report_path)
    except (OSError, TypeError, ValueError):
        for path in finalized:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ArtifactWriteError("Unable to write proxy-quality artifacts") from None
    finally:
        for temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _write_single_json(path: Path, payload: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        temporary = _stage_json(path, payload)
        temporary.replace(path)
    except (OSError, TypeError, ValueError):
        raise ArtifactWriteError("Unable to write direct-control artifact") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def run_direct_network_control(output_dir: Path) -> dict[str, object]:
    """Run one direct-network Google control in a separate artifact tree."""

    started_at = datetime.now(timezone.utc)
    artifact_dir = _make_artifact_directory(Path(output_dir) / "direct-control", started_at)
    screenshot_path = artifact_dir / "google.png"
    try:
        with tempfile.TemporaryDirectory(prefix="cloakbrowser-proxy-quality-direct-") as profile:
            raw_result = run_direct_google_control(Path(profile), screenshot_path)
    except OSError:
        raise ArtifactWriteError("Unable to prepare direct-control artifacts") from None

    result = raw_result if isinstance(raw_result, Mapping) else {}
    verdict = result.get("verdict")
    if verdict not in _SITE_VERDICTS["google"] - {"skipped"}:
        verdict = "unknown"
    captured = result.get("screenshot_captured") is True and screenshot_path.is_file()
    if captured:
        _sanitize_png_metadata(screenshot_path, set())
    else:
        try:
            screenshot_path.unlink(missing_ok=True)
        except OSError:
            raise ArtifactWriteError("Unable to remove incomplete direct-control screenshot") from None
    payload: dict[str, object] = {
        "control": "direct_network_google",
        "timestamp_utc": _timestamp_utc(started_at),
        "excluded_from_proxy_report": True,
        "google": {
            "verdict": verdict,
            "screenshot_captured": captured,
            "screenshot": "google.png" if captured else None,
        },
    }
    artifact_path = artifact_dir / "direct-control.json"
    _write_single_json(artifact_path, payload)
    return {**payload, "artifact_path": str(artifact_path)}


def run_proxy_quality_scan(
    proxy: str,
    output_dir: Path,
    *,
    browser_checks: bool,
    ipinfo_token: str | None,
) -> dict[str, object]:
    """Run one scan and return its safe report plus the report artifact path."""

    validate_proxy_url(proxy)
    secrets = _build_secret_set(proxy, ipinfo_token)
    try:
        assert_no_secrets(str(Path(output_dir)), secrets)
    except ValueError:
        raise ArtifactWriteError("Unsafe artifact output path was rejected") from None
    started_at = datetime.now(timezone.utc)
    connectivity = _safe_connectivity(resolve_exit_ip(proxy))
    exit_ip = connectivity.get("exit_ip")
    if not isinstance(exit_ip, str):
        raise ProxyConnectivityError("The proxy exit IP was unavailable")

    cache = DatasetCache(Path(output_dir) / ".cache", _CACHE_MAX_AGE)
    intelligence = collect_intelligence(exit_ip, cache, ipinfo_token)
    signals = _signals(intelligence.get("signals") if isinstance(intelligence, Mapping) else None)
    classification = classify_network(signals)

    artifact_dir = _make_artifact_directory(Path(output_dir), started_at)
    if browser_checks:
        try:
            with tempfile.TemporaryDirectory(prefix="cloakbrowser-proxy-quality-") as profile:
                browser_result = run_browser_checks(
                    proxy,
                    Path(profile),
                    artifact_dir,
                    expected_exit_ip=exit_ip,
                )
        except OSError:
            raise ArtifactWriteError("Unable to prepare browser artifacts") from None
        _sanitize_browser_screenshots(artifact_dir, browser_result, secrets)
        identity_alignment = _safe_identity(
            browser_result.get("identity") if isinstance(browser_result, Mapping) else None
        )
        site_outcomes = _site_outcomes(browser_result)
    else:
        identity_alignment = {"status": "unknown", "aligned": None, "complete": False}
        site_outcomes = {
            "cloudflare": {
                "verdict": "skipped",
                "screenshot_captured": False,
                "screenshot": None,
            },
            "google": {
                "verdict": "skipped",
                "screenshot_captured": False,
                "screenshot": None,
            },
        }

    intelligence_mapping = intelligence if isinstance(intelligence, Mapping) else {}
    reputation_intelligence: dict[str, object] = {
        "high_confidence_matches": _safe_matches(
            intelligence_mapping.get("high_confidence_matches")
        ),
        "other_matches": _safe_matches(intelligence_mapping.get("other_matches")),
    }
    required_source_status = _safe_required_source_status(
        intelligence_mapping.get("required_source_status")
    )
    required_sources_available = all(
        required_source_status[source] == "available"
        for source in _REQUIRED_REPUTATION_SOURCES
    )
    reputation_intelligence["required_source_status"] = required_source_status
    reputation_intelligence["required_sources_available"] = required_sources_available
    if reputation_intelligence["high_confidence_matches"] or reputation_intelligence["other_matches"]:
        reputation_intelligence["observation"] = "matches_observed"
    elif required_sources_available:
        reputation_intelligence["observation"] = "no_listed_abuse"
    else:
        reputation_intelligence["observation"] = "unavailable"
    sources_manifest = _safe_manifest(intelligence_mapping.get("manifest"))
    report: dict[str, object] = {
        "connectivity": connectivity,
        "classification": classification,
        "reputation_intelligence": reputation_intelligence,
        "identity_alignment": identity_alignment,
        "site_outcomes": site_outcomes,
        "proxy": redact_proxy(proxy),
        "timestamp_utc": _timestamp_utc(started_at),
        "sources_manifest": sources_manifest,
        "related_checks": {
            "pixelscan": {"url": _PIXELSCAN_URL, "automatic": False},
            "cloudflare_turnstile_demo": {
                "third_party": True,
                "scope": "observed demo outcome only; not a universal Cloudflare verdict",
            },
        },
    }
    report["summary"] = summarize_report(report)

    report_path = artifact_dir / "report.json"
    console_payload: dict[str, object] = {
        "proxy": report["proxy"],
        "summary": report["summary"],
        "artifact_path": str(report_path),
    }
    _assert_payloads_safe(report, console_payload, secrets)
    _write_artifacts(report_path, report, sources_manifest)
    return {**report, "artifact_path": str(report_path)}


def _error(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_cli_arguments(arguments: list[str]) -> tuple[Path, bool]:
    output_dir = _DEFAULT_OUTPUT_DIR
    direct_control = False
    output_seen = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--direct-control" and not direct_control:
            direct_control = True
            index += 1
            continue
        if argument == "--output-dir" and not output_seen and index + 1 < len(arguments):
            raw_path = arguments[index + 1]
            if not raw_path or raw_path.startswith("-") or "://" in raw_path or "@" in raw_path:
                raise ValueError("Invalid output directory option")
            output_dir = Path(raw_path)
            output_seen = True
            index += 2
            continue
        raise ValueError("Unsupported proxy-quality argument")
    return output_dir, direct_control


def main(argv: list[str] | None = None) -> int:
    """Run from environment-only configuration with stable exit codes."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        output_dir, direct_control = _parse_cli_arguments(arguments)
    except ValueError:
        _error("proxy-quality accepts only --output-dir PATH; proxy values must use the environment")
        return 2

    if direct_control:
        try:
            result = run_direct_network_control(output_dir)
        except ArtifactWriteError:
            _error("Proxy-quality direct-control artifact creation failed")
            return 4
        except Exception:
            _error("Unexpected proxy-quality direct-control failure")
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0

    proxy = os.environ.get("CLOAK_TEST_PROXY")
    if not proxy or not proxy.strip():
        _error("CLOAK_TEST_PROXY is required")
        return 2

    skip_browser = os.environ.get("PROXY_QUALITY_SKIP_BROWSER", "0")
    if skip_browser not in {"0", "1"}:
        _error("PROXY_QUALITY_SKIP_BROWSER must be 0 or 1")
        return 2
    ipinfo_token = os.environ.get("IPINFO_TOKEN") or None

    try:
        result = run_proxy_quality_scan(
            proxy,
            output_dir,
            browser_checks=skip_browser != "1",
            ipinfo_token=ipinfo_token,
        )
        console_payload = {
            "proxy": result["proxy"],
            "summary": result["summary"],
            "artifact_path": result["artifact_path"],
        }
        assert_no_secrets(console_payload, _build_secret_set(proxy, ipinfo_token))
    except ProxyConnectivityError:
        _error("Proxy connectivity check failed")
        return 3
    except ArtifactWriteError:
        _error("Proxy-quality artifact creation failed")
        return 4
    except ValueError:
        _error("Invalid proxy-quality configuration")
        return 2
    except Exception:
        _error("Unexpected proxy-quality failure")
        return 1

    print(json.dumps(console_payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
