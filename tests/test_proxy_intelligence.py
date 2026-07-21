"""Deterministic tests for proxy connectivity and dataset caching."""

from datetime import timedelta
import hashlib
import json
from pathlib import Path
import traceback

import pytest

import benchmarks.proxy_intelligence as intelligence

from benchmarks.proxy_intelligence import (
    DatasetCache,
    ProxyConnectivityError,
    resolve_exit_ip,
    sha256_file,
    validate_proxy_url,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "proxy_quality"


def test_validate_proxy_rejects_credentials_without_host():
    with pytest.raises(ValueError, match="host"):
        validate_proxy_url("socks5://user:pass@")


@pytest.mark.parametrize("value", ["socks4://proxy.example:1080", "socks4a://proxy.example:1080"])
def test_validate_proxy_rejects_unsupported_socks_schemes(value):
    with pytest.raises(ValueError, match="supported"):
        validate_proxy_url(value)


@pytest.mark.parametrize("value", ["", "proxy.example:1080", "http:///missing-host"])
def test_validate_proxy_rejects_malformed_urls(value):
    with pytest.raises(ValueError):
        validate_proxy_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://proxy.example",
        "socks5://proxy.example:1080/path",
        "socks5://proxy.example:1080?credential=sample",
        "socks5://proxy.example:1080#credential",
        "http://user:pass@proxy.example:8080/",
    ],
)
def test_validate_proxy_rejects_incomplete_or_suffixed_endpoints(value):
    with pytest.raises(ValueError):
        validate_proxy_url(value)


def test_validate_proxy_accepts_last_at_password_and_encoded_delimiters():
    validate_proxy_url("socks5://user:p@ss@proxy.example:1080")
    validate_proxy_url("http://user%40name:pass%2Fword@proxy.example:8080")


def test_validate_proxy_scrubs_urllib_cause_for_nfkc_invalid_authority():
    malformed = "http://sample-user\uff1asample-password@proxy.example:8080"

    with pytest.raises(ValueError) as exc_info:
        validate_proxy_url(malformed)

    rendered_error = "".join(traceback.format_exception(exc_info.value))
    assert "sample-user" not in rendered_error
    assert "sample-password" not in rendered_error
    assert malformed not in rendered_error


def test_socks_client_construction_error_is_redacted_and_includes_install_guidance(monkeypatch):
    proxy = "socks5://user:password@proxy.example:1080"

    def unavailable_client(**_kwargs):
        raise ImportError(f"missing socks support for {proxy}")

    monkeypatch.setattr("benchmarks.proxy_intelligence.httpx.Client", unavailable_client)

    with pytest.raises(ProxyConnectivityError) as exc_info:
        resolve_exit_ip(proxy)

    rendered_error = "".join(traceback.format_exception(exc_info.value))
    assert "user" not in rendered_error
    assert "password" not in rendered_error
    assert 'pip install -e ".[geoip]"' in rendered_error


def test_resolve_exit_ip_selects_majority_and_records_disagreement(monkeypatch):
    responses = iter(["203.0.113.10", "203.0.113.10", "203.0.113.11"])
    monkeypatch.setattr(
        "benchmarks.proxy_intelligence._fetch_echo_ip", lambda *args, **kwargs: next(responses)
    )

    result = resolve_exit_ip("socks5://u:p@proxy.example:1080", attempts=3)

    assert result["exit_ip"] == "203.0.113.10"
    assert result["exit_ip_agreement"] is False
    assert len(result["latency_ms"]) == 3
    assert result["latency_median_ms"] == sorted(result["latency_ms"])[1]
    assert [item["source"] for item in result["echo_services"]] == [
        "ipify",
        "aws_checkip",
        "ipify",
    ]
    assert result["country_consistency"] == "unavailable"


def test_resolve_exit_ip_alternates_three_default_echo_endpoints(monkeypatch):
    queried_urls: list[str] = []

    def fake_fetch(_client, url):
        queried_urls.append(url)
        return "203.0.113.10"

    monkeypatch.setattr("benchmarks.proxy_intelligence._fetch_echo_ip", fake_fetch)

    result = resolve_exit_ip("http://proxy.example:8080")

    assert result["exit_ip_agreement"] is True
    assert queried_urls == [
        "https://api.ipify.org?format=json",
        "https://checkip.amazonaws.com/",
        "https://api.ipify.org?format=json",
    ]


def test_resolve_exit_ip_requires_two_successful_responses(monkeypatch):
    responses = iter(["203.0.113.10", RuntimeError("offline"), RuntimeError("offline")])

    def fake_fetch(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("benchmarks.proxy_intelligence._fetch_echo_ip", fake_fetch)

    with pytest.raises(ProxyConnectivityError, match="successful"):
        resolve_exit_ip("http://proxy.example:8080")


def test_resolve_exit_ip_requires_success_from_both_independent_services(monkeypatch):
    def fake_fetch(_client, url):
        if url == intelligence._ECHO_ENDPOINTS[1]:
            raise RuntimeError("second service unavailable")
        return "203.0.113.10"

    monkeypatch.setattr(intelligence, "_fetch_echo_ip", fake_fetch)

    with pytest.raises(ProxyConnectivityError, match="independent"):
        resolve_exit_ip("http://proxy.example:8080")


def test_resolve_exit_ip_accepts_one_success_from_each_service(monkeypatch):
    monkeypatch.setattr(
        intelligence,
        "_fetch_echo_ip",
        lambda _client, _url: "203.0.113.10",
    )

    result = resolve_exit_ip("http://proxy.example:8080", attempts=2)

    assert result["exit_ip_agreement"] is True
    assert {item["source"] for item in result["echo_services"]} == {
        "ipify",
        "aws_checkip",
    }


def test_resolve_exit_ip_records_all_three_attempt_outcomes_without_error_text(monkeypatch):
    calls = 0

    def fake_fetch(_client, _url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("credential-bearing transport detail")
        return "203.0.113.10"

    monkeypatch.setattr(intelligence, "_fetch_echo_ip", fake_fetch)

    result = resolve_exit_ip("http://proxy.example:8080")

    assert result["echo_services"] == [
        {"source": "ipify", "status": "unavailable"},
        {
            "source": "aws_checkip",
            "status": "available",
            "ip": "203.0.113.10",
            "latency_ms": result["latency_ms"][0],
        },
        {
            "source": "ipify",
            "status": "available",
            "ip": "203.0.113.10",
            "latency_ms": result["latency_ms"][1],
        },
    ]
    assert "credential-bearing" not in repr(result)


def test_sha256_file_hashes_file_contents(tmp_path):
    target = tmp_path / "dataset.txt"
    target.write_bytes(b"proxy-quality\n")

    assert sha256_file(target) == hashlib.sha256(b"proxy-quality\n").hexdigest()


def test_dataset_provenance_rejects_missing_or_mismatched_metadata(tmp_path):
    target = tmp_path / "dataset.txt"
    target.write_text("203.0.113.0/24\n", encoding="utf-8")

    with pytest.raises(ValueError, match="provenance"):
        intelligence._dataset_provenance(target)

    metadata = {
        "url": "https://example.invalid/dataset.txt",
        "retrieved_at": "2026-07-21T00:00:00Z",
        "sha256": "0" * 64,
        "byte_count": target.stat().st_size,
    }
    target.with_name(f"{target.name}.meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="provenance"):
        intelligence._dataset_provenance(target)

    metadata.update(
        {
            "sha256": sha256_file(target),
            "url": "https://wrong.example/dataset.txt",
        }
    )
    target.with_name(f"{target.name}.meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="provenance"):
        intelligence._dataset_provenance(
            target, "https://example.invalid/dataset.txt"
        )


def test_required_source_with_zero_valid_networks_is_unavailable(tmp_path):
    target = tmp_path / "ipsum.txt"
    target.write_text("<html>rate limited</html>\n", encoding="utf-8")
    target.with_name(f"{target.name}.meta.json").write_text(
        json.dumps(
            {
                "url": "https://example.invalid/ipsum.txt",
                "retrieved_at": "2026-07-21T00:00:00Z",
                "sha256": sha256_file(target),
                "byte_count": target.stat().st_size,
            }
        ),
        encoding="utf-8",
    )

    class Cache:
        def get(self, _url: str, _name: str) -> Path:
            return target

    result = intelligence._collect_network_source(
        "203.0.113.80",
        Cache(),
        "ipsum",
        "https://example.invalid/ipsum.txt",
        "ipsum.txt",
        minimum_score=3,
    )

    assert result["status"] == "unavailable"
    assert result["matches"] == []


def test_cache_reuses_fresh_file(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(hours=24))
    existing = tmp_path / "ipsum.txt"
    existing.write_text("203.0.113.0/24\t3\n", encoding="utf-8")
    monkeypatch.setattr(
        "benchmarks.proxy_intelligence._download_atomic",
        lambda *args: (_ for _ in ()).throw(AssertionError("download should not run")),
    )

    assert cache.get("https://example.invalid/ipsum.txt", "ipsum.txt") == existing


def test_cache_hashes_then_replaces_and_writes_safe_metadata(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(seconds=0))
    target = tmp_path / "ipsum.txt"
    target.write_text("older\n", encoding="utf-8")
    calls: list[Path] = []

    def fake_download(_url: str, temporary: Path) -> None:
        calls.append(temporary)
        temporary.write_text("203.0.113.0/24\t3\n", encoding="utf-8")

    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", fake_download)

    assert cache.get("https://user:password@example.invalid/ipsum.txt", "ipsum.txt") == target
    metadata = json.loads((tmp_path / "ipsum.txt.meta.json").read_text(encoding="utf-8"))

    assert calls == [tmp_path / "ipsum.txt.tmp"]
    assert target.read_text(encoding="utf-8") == "203.0.113.0/24\t3\n"
    assert metadata["url"] == "https://example.invalid/ipsum.txt"
    assert metadata["sha256"] == sha256_file(target)
    assert metadata["byte_count"] == target.stat().st_size
    assert metadata["retrieved_at"].endswith("Z")


def test_cache_preserves_bracketed_ipv6_host_in_sanitized_metadata_url(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(seconds=0))

    def fake_download(_url: str, temporary: Path) -> None:
        temporary.write_text("2001:db8::/32\n", encoding="utf-8")

    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", fake_download)

    cache.get("https://user:password@[2001:db8::1]:8443/ipsum.txt", "ipsum.txt")

    metadata = json.loads((tmp_path / "ipsum.txt.meta.json").read_text(encoding="utf-8"))
    assert metadata["url"] == "https://[2001:db8::1]:8443/ipsum.txt"


def test_cache_removes_temporary_file_after_failure_and_keeps_existing_file(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(seconds=0))
    target = tmp_path / "ipsum.txt"
    target.write_text("older\n", encoding="utf-8")

    def failed_download(_url: str, temporary: Path) -> None:
        temporary.write_text("partial", encoding="utf-8")
        raise RuntimeError("download failed for https://user:password@example.invalid/ipsum.txt")

    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", failed_download)

    with pytest.raises(RuntimeError) as exc_info:
        cache.get("https://example.invalid/ipsum.txt", "ipsum.txt")

    assert "user:password" not in str(exc_info.value)
    assert target.read_text(encoding="utf-8") == "older\n"
    assert not (tmp_path / "ipsum.txt.tmp").exists()


def test_cache_rolls_back_data_and_metadata_when_metadata_replacement_fails(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(seconds=0))
    target = tmp_path / "ipsum.txt"
    metadata = tmp_path / "ipsum.txt.meta.json"
    target.write_text("older-data\n", encoding="utf-8")
    metadata.write_text('{"sha256": "older-hash"}\n', encoding="utf-8")

    def fake_download(_url: str, temporary: Path) -> None:
        temporary.write_text("new-data\n", encoding="utf-8")

    original_replace = Path.replace

    def fail_new_metadata_replace(self: Path, destination: Path) -> Path:
        if self == metadata.with_name(f"{metadata.name}.tmp") and destination == metadata:
            raise OSError("metadata replacement failed")
        return original_replace(self, destination)

    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", fake_download)
    monkeypatch.setattr(Path, "replace", fail_new_metadata_replace)

    with pytest.raises(RuntimeError, match="Dataset download failed"):
        cache.get("https://example.invalid/ipsum.txt", "ipsum.txt")

    assert target.read_text(encoding="utf-8") == "older-data\n"
    assert metadata.read_text(encoding="utf-8") == '{"sha256": "older-hash"}\n'
    assert not (tmp_path / "ipsum.txt.tmp").exists()
    assert not (tmp_path / "ipsum.txt.meta.json.tmp").exists()
    assert not (tmp_path / "ipsum.txt.bak").exists()
    assert not (tmp_path / "ipsum.txt.meta.json.bak").exists()


def test_cache_keeps_new_complete_entry_when_backup_cleanup_fails(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(seconds=0))
    target = tmp_path / "ipsum.txt"
    metadata = tmp_path / "ipsum.txt.meta.json"
    metadata_backup = tmp_path / "ipsum.txt.meta.json.bak"
    target.write_text("older-data\n", encoding="utf-8")
    metadata.write_text('{"sha256": "older-hash"}\n', encoding="utf-8")

    def fake_download(_url: str, temporary: Path) -> None:
        temporary.write_text("new-data\n", encoding="utf-8")

    original_unlink = Path.unlink

    def fail_metadata_backup_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self == metadata_backup and self.exists():
            raise OSError("backup cleanup failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", fake_download)
    monkeypatch.setattr(Path, "unlink", fail_metadata_backup_cleanup)

    assert cache.get("https://example.invalid/ipsum.txt", "ipsum.txt") == target
    assert target.read_text(encoding="utf-8") == "new-data\n"
    assert json.loads(metadata.read_text(encoding="utf-8"))["sha256"] == sha256_file(target)
    assert metadata_backup.exists()


def test_parse_network_list_ignores_comments_blank_lines_and_low_ipsum_scores():
    networks = intelligence.parse_network_list(FIXTURE_ROOT / "ipsum.txt", minimum_score=3)

    assert [str(network) for network in networks] == [
        "198.51.100.0/24",
        "203.0.113.0/24",
        "2001:db8:1234::/48",
    ]


def test_match_networks_supports_ipv4_and_ipv6_cidrs():
    networks = intelligence.parse_network_list(FIXTURE_ROOT / "firehol_level1.netset")

    assert intelligence.match_networks("192.0.2.20", networks) == ["192.0.2.0/25"]
    assert intelligence.match_networks("2001:db8:abcd::20", networks) == [
        "2001:db8:abcd::/48"
    ]


def test_lookup_sapics_asn_uses_the_most_specific_matching_range():
    result = intelligence.lookup_sapics_asn(
        "203.0.113.80", FIXTURE_ROOT / "sapics_asn.csv"
    )

    assert result == {
        "source": "sapics",
        "asn": 64502,
        "asn_name": "Example Specific Documentation Network",
        "range_start": "203.0.113.64",
        "range_end": "203.0.113.127",
    }


def test_lookup_ipinfo_without_token_makes_no_network_call(monkeypatch):
    monkeypatch.setattr(
        intelligence.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )

    assert intelligence.lookup_ipinfo("203.0.113.80", None) is None


def test_lookup_ipinfo_preserves_structured_fields_without_serializing_token(monkeypatch):
    payload = json.loads((FIXTURE_ROOT / "ipinfo.json").read_text(encoding="utf-8"))
    payload["secret-token"] = "provider-controlled key"

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    requested_urls: list[str] = []

    def fake_get(url: str, **_kwargs):
        requested_urls.append(url)
        return Response()

    monkeypatch.setattr(intelligence.httpx, "get", fake_get)

    result = intelligence.lookup_ipinfo("203.0.113.80", "secret-token")

    assert result is not None
    assert result["source"] == "ipinfo"
    assert result["is_mobile"] is True
    assert result["is_hosting"] is False
    assert result["privacy"] == {"vpn": False, "proxy": False, "tor": False}
    assert result["carrier"] == {"name": "Example Carrier", "mcc": "001", "mnc": "01"}
    assert result["asn"] == "AS64502"
    assert result["asn_name"] == "Example Mobile Network"
    assert result["asn_type"] == "isp"
    assert "secret-token" not in repr(result)
    assert requested_urls == [
        "https://api.ipinfo.io/lite/203.0.113.80?token=secret-token"
    ]


def test_collect_intelligence_isolates_failures_and_selects_sapics_asset_from_file_list(
    tmp_path, monkeypatch
):
    package_metadata = tmp_path / "sapics-package.json"
    package_metadata.write_text(
        json.dumps({"tags": {"latest": "2.3.2026061719"}}), encoding="utf-8"
    )
    package_files = tmp_path / "sapics-files.json"
    package_files.write_text(
        json.dumps(
            {
                "files": [
                    {"name": "/iptoasn-asn-ipv4-num.csv"},
                    {"name": "/iptoasn-asn-ipv6-num.csv"},
                    {"name": "/iptoasn-asn-ipv6.csv"},
                    {"name": "/iptoasn-asn-ipv4.csv"},
                ]
            }
        ),
        encoding="utf-8",
    )
    requested_urls: list[str] = []
    route_by_url = {
        intelligence.IPSUM_DATASET_URL: FIXTURE_ROOT / "ipsum.txt",
        intelligence.FIREHOL_LEVEL1_DATASET_URL: FIXTURE_ROOT / "firehol_level1.netset",
        intelligence.SAPICS_PACKAGE_METADATA_URL: package_metadata,
        intelligence.SAPICS_PACKAGE_FILES_URL.format(version="2.3.2026061719"): package_files,
        intelligence.SAPICS_DATASET_URL.format(
            version="2.3.2026061719", asset="iptoasn-asn-ipv4.csv"
        ): FIXTURE_ROOT / "sapics_asn.csv",
    }
    cache = DatasetCache(tmp_path / "cache", timedelta(days=1))

    def fake_cache_get(url: str, _name: str) -> Path:
        requested_urls.append(url)
        if url == intelligence.FIREHOL_LEVEL2_DATASET_URL:
            raise RuntimeError("source unavailable")
        return route_by_url[url]

    ipinfo_payload = json.loads((FIXTURE_ROOT / "ipinfo.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(cache, "get", fake_cache_get)
    monkeypatch.setattr(
        intelligence,
        "_dataset_provenance",
        lambda path, *_expected: ("2026-07-21T00:00:00Z", sha256_file(path)),
    )
    monkeypatch.setattr(
        intelligence,
        "lookup_ipinfo",
        lambda _ip, _token: {"source": "ipinfo", **ipinfo_payload},
    )

    result = intelligence.collect_intelligence("203.0.113.80", cache, "secret-token")
    manifest = {entry["source"]: entry for entry in result["manifest"]}

    assert set(manifest) == {
        "ipsum",
        "firehol_level1",
        "firehol_level2",
        "sapics",
        "ipinfo",
    }
    assert manifest["firehol_level2"]["status"] == "unavailable"
    assert manifest["ipsum"]["status"] == "available"
    assert manifest["firehol_level1"]["status"] == "available"
    assert manifest["sapics"]["status"] == "available"
    assert manifest["sapics"]["version"] == "2.3.2026061719"
    assert manifest["ipinfo"]["status"] == "available"
    assert manifest["ipsum"]["matches"] == ["203.0.113.0/24"]
    assert result["signals"][0]["asn"] == 64502
    assert result["signals"][1]["is_mobile"] is True
    assert result["high_confidence_matches"] == [
        {
            "source": "ipsum",
            "network": "203.0.113.0/24",
            "category": "aggregated_abuse",
            "granularity": "cidr",
        }
    ]
    assert result["other_matches"] == []
    assert result["required_source_status"] == {
        "ipsum": "available",
        "firehol_level1": "available",
        "firehol_level2": "unavailable",
    }
    assert result["required_sources_available"] is False
    assert any(url.endswith("/iptoasn-asn-ipv4.csv") for url in requested_urls)
    assert not any(url.endswith("-ipv4-num.csv") for url in requested_urls)
    assert "secret-token" not in repr(result)


@pytest.mark.parametrize(
    ("network", "expected"),
    [("203.0.113.80/32", "exact_ip"), ("203.0.113.0/24", "cidr")],
)
def test_reputation_match_records_category_and_granularity(network, expected):
    assert intelligence.reputation_match(
        "203.0.113.80",
        source="fixture",
        network=network,
        category="conservative_blocklist",
    ) == {
        "source": "fixture",
        "network": network,
        "category": "conservative_blocklist",
        "granularity": expected,
    }


def test_source_catalog_records_repository_dataset_and_license_urls():
    assert set(intelligence.SOURCE_CATALOG) == {
        "ipsum",
        "firehol_level1",
        "firehol_level2",
        "sapics",
        "ipinfo",
    }
    assert all(
        {"repository_url", "dataset_url", "license_url"} <= metadata.keys()
        for metadata in intelligence.SOURCE_CATALOG.values()
    )
    assert intelligence.SAPICS_RESOLVED_VERSION == "2.3.2026061719"


def test_unavailable_sapics_asset_still_records_resolved_package_version(tmp_path, monkeypatch):
    package_metadata = tmp_path / "sapics-package.json"
    package_metadata.write_text(
        json.dumps({"tags": {"latest": "2.3.2026061719"}}), encoding="utf-8"
    )
    package_files = tmp_path / "sapics-files.json"
    package_files.write_text(
        json.dumps({"files": [{"name": "/iptoasn-asn-ipv4.csv"}]}), encoding="utf-8"
    )
    files_url = intelligence.SAPICS_PACKAGE_FILES_URL.format(version="2.3.2026061719")
    cache = DatasetCache(tmp_path / "cache", timedelta(days=1))

    def fake_cache_get(url: str, _name: str) -> Path:
        if url == intelligence.SAPICS_PACKAGE_METADATA_URL:
            return package_metadata
        if url == files_url:
            return package_files
        raise RuntimeError("offline")

    monkeypatch.setattr(cache, "get", fake_cache_get)
    monkeypatch.setattr(
        intelligence.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )

    result = intelligence.collect_intelligence("203.0.113.80", cache, None)
    manifest = {entry["source"]: entry for entry in result["manifest"]}

    assert manifest["sapics"]["status"] == "unavailable"
    assert manifest["sapics"]["version"] == "2.3.2026061719"
    assert manifest["ipinfo"]["status"] == "unavailable"
