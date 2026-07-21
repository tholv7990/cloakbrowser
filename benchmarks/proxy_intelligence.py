"""Credential-safe connectivity and local cache primitives for proxy scans."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from benchmarks.proxy_quality_models import redact_proxy


_ECHO_ENDPOINTS = (
    "https://api.ipify.org?format=json",
    "https://checkip.amazonaws.com/",
)
_ECHO_SOURCE_NAMES = {
    _ECHO_ENDPOINTS[0]: "ipify",
    _ECHO_ENDPOINTS[1]: "aws_checkip",
}
_SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})

IPSUM_REPOSITORY_URL = "https://github.com/stamparm/ipsum"
IPSUM_DATASET_URL = "https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt"
IPSUM_LICENSE_URL = "https://github.com/stamparm/ipsum/blob/master/LICENSE"

FIREHOL_REPOSITORY_URL = "https://github.com/firehol/blocklist-ipsets"
FIREHOL_LEVEL1_DATASET_URL = (
    "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset"
)
FIREHOL_LEVEL2_DATASET_URL = (
    "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level2.netset"
)
# FireHOL aggregates upstream lists with distinct terms; its repository is the
# attribution index rather than claiming one license for every combined entry.
FIREHOL_LICENSE_URL = "https://github.com/firehol/blocklist-ipsets"

SAPICS_REPOSITORY_URL = "https://github.com/sapics/ip-location-db"
SAPICS_PACKAGE_METADATA_URL = (
    "https://data.jsdelivr.com/v1/package/npm/%40ip-location-db%2Fiptoasn-asn"
)
SAPICS_PACKAGE_FILES_URL = (
    "https://data.jsdelivr.com/v1/package/npm/"
    "%40ip-location-db%2Fiptoasn-asn@{version}/flat"
)
SAPICS_DATASET_URL = (
    "https://cdn.jsdelivr.net/npm/@ip-location-db/iptoasn-asn@{version}/{asset}"
)
SAPICS_LICENSE_URL = "https://opendatacommons.org/licenses/pddl/1-0/"
# Resolved from the jsDelivr package metadata and file list on 2026-07-21.
SAPICS_RESOLVED_VERSION = "2.3.2026061719"

IPINFO_REPOSITORY_URL = "https://github.com/ipinfo"
IPINFO_DATASET_URL = "https://api.ipinfo.io/lite/{ip}"
IPINFO_LICENSE_URL = "https://ipinfo.io/terms-of-service"
_IPINFO_REQUEST_URL = "https://api.ipinfo.io/lite/{ip}?token={token}"

SOURCE_CATALOG: dict[str, dict[str, str]] = {
    "ipsum": {
        "repository_url": IPSUM_REPOSITORY_URL,
        "dataset_url": IPSUM_DATASET_URL,
        "license_url": IPSUM_LICENSE_URL,
    },
    "firehol_level1": {
        "repository_url": FIREHOL_REPOSITORY_URL,
        "dataset_url": FIREHOL_LEVEL1_DATASET_URL,
        "license_url": FIREHOL_LICENSE_URL,
    },
    "firehol_level2": {
        "repository_url": FIREHOL_REPOSITORY_URL,
        "dataset_url": FIREHOL_LEVEL2_DATASET_URL,
        "license_url": FIREHOL_LICENSE_URL,
    },
    "sapics": {
        "repository_url": SAPICS_REPOSITORY_URL,
        "dataset_url": SAPICS_DATASET_URL,
        "license_url": SAPICS_LICENSE_URL,
    },
    "ipinfo": {
        "repository_url": IPINFO_REPOSITORY_URL,
        "dataset_url": IPINFO_DATASET_URL,
        "license_url": IPINFO_LICENSE_URL,
    },
}


class ProxyConnectivityError(RuntimeError):
    """Raised when fewer than two independent proxy echo requests succeed."""


def validate_proxy_url(value: str) -> None:
    """Raise ``ValueError`` unless *value* is a complete supported proxy URL.

    Error messages intentionally omit the supplied URL so proxy credentials can
    never escape through configuration errors.
    """

    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("Proxy URL must be a non-empty URL with a host")
    if any(ord(character) < 32 or character.isspace() for character in value):
        raise ValueError("Proxy URL is malformed")
    try:
        parsed = urlsplit(value)
        # Accessing port validates malformed values such as ``:not-a-port``.
        port = parsed.port
    except ValueError:
        # ``urllib`` includes the complete malformed netloc in some exception
        # messages (notably NFKC-delimiter failures), so never retain its cause.
        raise ValueError("Proxy URL is malformed") from None
    if parsed.scheme.lower() not in _SUPPORTED_PROXY_SCHEMES:
        raise ValueError("Proxy URL must use a supported scheme")
    if not parsed.hostname:
        raise ValueError("Proxy URL must include a host")
    if port is None or port <= 0:
        raise ValueError("Proxy URL must include a valid port")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Proxy URL must contain only scheme, authority, and port")


def _fetch_echo_ip(client: httpx.Client, url: str) -> str:
    """Fetch a single echo response and return its unnormalised IP string."""

    response = client.get(url)
    response.raise_for_status()
    if url == _ECHO_ENDPOINTS[0]:
        payload: Any = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("ip"), str):
            raise ValueError("Echo service returned no IP address")
        return payload["ip"]
    return response.text.strip()


def _normalized_ip(value: str) -> str:
    """Return the canonical IP representation or propagate a parse failure."""

    return str(ipaddress.ip_address(value.strip()))


def resolve_exit_ip(proxy: str, *, attempts: int = 3) -> dict[str, object]:
    """Resolve a proxy's public IP using alternating independent echo services.

    A SOCKS URL requires the optional ``socksio`` transport.  Install it with
    ``pip install -e ".[geoip]"`` if httpx reports it unavailable.
    """

    validate_proxy_url(proxy)
    if attempts < 1:
        raise ValueError("At least one echo attempt is required")

    parsed_proxy = urlsplit(proxy)
    try:
        client = httpx.Client(proxy=proxy, timeout=10.0, follow_redirects=False)
    except Exception:
        if parsed_proxy.scheme.lower().startswith("socks"):
            raise ProxyConnectivityError(
                "SOCKS proxy support is unavailable for "
                f"{redact_proxy(proxy)}; install it with pip install -e \".[geoip]\"."
            ) from None
        raise ProxyConnectivityError("Unable to initialize proxy connectivity client") from None

    successful_ips: list[str] = []
    latencies: list[float] = []
    observations: list[dict[str, object]] = []
    with client:
        for index in range(attempts):
            endpoint = _ECHO_ENDPOINTS[index % len(_ECHO_ENDPOINTS)]
            started = perf_counter()
            try:
                raw_ip = _fetch_echo_ip(client, endpoint)
                normalized_ip = _normalized_ip(raw_ip)
                latency_ms = round((perf_counter() - started) * 1000, 3)
                successful_ips.append(normalized_ip)
                latencies.append(latency_ms)
                observations.append(
                    {
                        "source": _ECHO_SOURCE_NAMES[endpoint],
                        "status": "available",
                        "ip": normalized_ip,
                        "latency_ms": latency_ms,
                    }
                )
            except Exception:
                # Individual echo failures are expected with flaky proxies.  Do
                # not retain exception text because transport errors can expose
                # credential-bearing URLs.
                observations.append(
                    {
                        "source": _ECHO_SOURCE_NAMES[endpoint],
                        "status": "unavailable",
                    }
                )
                continue

    if len(successful_ips) < 2:
        raise ProxyConnectivityError("Fewer than two successful echo responses were received")
    observed_sources = {
        str(item["source"])
        for item in observations
        if item.get("status") == "available"
    }
    if observed_sources != set(_ECHO_SOURCE_NAMES.values()):
        raise ProxyConnectivityError("Both independent echo services must succeed")

    counts = Counter(successful_ips)
    # ``max`` preserves first-observed order for tied counts, avoiding a
    # nondeterministic set-based selection.
    majority_ip = max(successful_ips, key=lambda ip: counts[ip])
    return {
        "success": True,
        "exit_ip": majority_ip,
        "exit_ip_agreement": len(set(successful_ips)) == 1,
        "latency_ms": latencies,
        "latency_median_ms": round(float(median(latencies)), 3),
        "echo_services": observations,
        # The two deliberately minimal echo services do not return geography.
        # Keep this explicit rather than fabricating agreement from ASN data.
        "country_consistency": "unavailable",
    }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_dataset_url(url: str) -> str:
    """Remove userinfo before a dataset URL reaches cache metadata."""

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))


def _download_atomic(url: str, temporary: Path) -> None:
    """Download *url* to the supplied temporary sibling path."""

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        temporary.write_bytes(response.content)


class DatasetCache:
    """Filesystem cache whose replacement leaves an older file intact on failure."""

    def __init__(self, root: Path, max_age: timedelta):
        self.root = Path(root)
        self.max_age = max_age

    def _is_fresh(self, path: Path) -> bool:
        if not path.is_file():
            return False
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - modified <= self.max_age

    def get(self, url: str, name: str) -> Path:
        """Return a fresh cached dataset, downloading it atomically if needed."""

        requested = Path(name)
        if requested.name != name or name in {"", ".", ".."}:
            raise ValueError("Dataset name must be a simple file name")

        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        if self._is_fresh(target):
            return target

        temporary = target.with_name(f"{target.name}.tmp")
        metadata = target.with_name(f"{target.name}.meta.json")
        metadata_temporary = metadata.with_name(f"{metadata.name}.tmp")
        backup = target.with_name(f"{target.name}.bak")
        metadata_backup = metadata.with_name(f"{metadata.name}.bak")
        had_target = target.exists()
        had_metadata = metadata.exists()
        target_replaced = False
        metadata_replaced = False
        try:
            temporary.unlink(missing_ok=True)
            metadata_temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
            metadata_backup.unlink(missing_ok=True)
            _download_atomic(url, temporary)
            digest = sha256_file(temporary)
            byte_count = temporary.stat().st_size
            cache_metadata = {
                "url": _safe_dataset_url(url),
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "sha256": digest,
                "byte_count": byte_count,
            }
            metadata_temporary.write_text(
                json.dumps(cache_metadata, sort_keys=True) + "\n", encoding="utf-8"
            )
            # Hashing and metadata preparation happen before the data file can
            # replace an older valid cache entry.  Move both previous files out
            # first so a later metadata replacement failure can be rolled back.
            if had_target:
                target.replace(backup)
            if had_metadata:
                metadata.replace(metadata_backup)
            temporary.replace(target)
            target_replaced = True
            metadata_temporary.replace(metadata)
            metadata_replaced = True
        except Exception:
            temporary.unlink(missing_ok=True)
            metadata_temporary.unlink(missing_ok=True)
            if target_replaced:
                target.unlink(missing_ok=True)
            if metadata_replaced:
                metadata.unlink(missing_ok=True)
            if had_target and backup.exists():
                backup.replace(target)
            if had_metadata and metadata_backup.exists():
                metadata_backup.replace(metadata)
            backup.unlink(missing_ok=True)
            metadata_backup.unlink(missing_ok=True)
            raise RuntimeError("Dataset download failed") from None

        # Both new files are now published as a complete pair.  Cleanup cannot
        # roll back this committed cache generation; retain backups if the
        # filesystem refuses to delete them.
        for stale_backup in (backup, metadata_backup):
            try:
                stale_backup.unlink(missing_ok=True)
            except OSError:
                pass
        return target


def parse_network_list(
    path: Path, *, minimum_score: int | None = None
) -> list[ipaddress._BaseNetwork]:
    """Parse an IP/CIDR list, optionally requiring an IPsum-style score."""

    networks: list[ipaddress._BaseNetwork] = []
    with Path(path).open(encoding="utf-8") as stream:
        for raw_line in stream:
            line = raw_line.partition("#")[0].strip()
            if not line:
                continue
            fields = line.split()
            if minimum_score is not None:
                if len(fields) < 2:
                    continue
                try:
                    score = int(fields[1])
                except ValueError:
                    continue
                if score < minimum_score:
                    continue
            try:
                networks.append(ipaddress.ip_network(fields[0], strict=False))
            except ValueError:
                # Public blocklists occasionally contain non-network metadata.
                continue
    return networks


def match_networks(
    ip: str, networks: list[ipaddress._BaseNetwork]
) -> list[str]:
    """Return canonical networks from *networks* that contain *ip*."""

    address = ipaddress.ip_address(ip)
    return [
        str(network)
        for network in networks
        if network.version == address.version and address in network
    ]


def reputation_match(
    ip: str, *, source: str, network: str, category: str
) -> dict[str, str]:
    """Build one normalized, source-attributed reputation match record."""

    address = ipaddress.ip_address(ip)
    parsed_network = ipaddress.ip_network(network, strict=False)
    if parsed_network.version != address.version or address not in parsed_network:
        raise ValueError("Reputation network does not contain the observed IP")
    return {
        "source": source,
        "network": str(parsed_network),
        "category": category,
        "granularity": (
            "exact_ip" if parsed_network.prefixlen == parsed_network.max_prefixlen else "cidr"
        ),
    }


def lookup_sapics_asn(ip: str, path: Path) -> dict[str, object] | None:
    """Return the narrowest inclusive sapics ASN range containing *ip*."""

    address = ipaddress.ip_address(ip)
    best: tuple[int, dict[str, object]] | None = None
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) < 4 or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            try:
                range_start = ipaddress.ip_address(row[0].strip())
                range_end = ipaddress.ip_address(row[1].strip())
            except ValueError:
                continue
            if (
                range_start.version != address.version
                or range_end.version != address.version
                or int(range_start) > int(range_end)
                or not (int(range_start) <= int(address) <= int(range_end))
            ):
                continue
            raw_asn = row[2].strip()
            numeric_asn = raw_asn[2:] if raw_asn.upper().startswith("AS") else raw_asn
            asn: object = int(numeric_asn) if numeric_asn.isdigit() else raw_asn
            record: dict[str, object] = {
                "source": "sapics",
                "asn": asn,
                "asn_name": ",".join(row[3:]).strip(),
                "range_start": str(range_start),
                "range_end": str(range_end),
            }
            width = int(range_end) - int(range_start)
            if best is None or width < best[0]:
                best = (width, record)
    return best[1] if best is not None else None


def _redact_token(value: object, token: str) -> object:
    """Recursively remove a token from provider-controlled response data."""

    if isinstance(value, str):
        sanitized = value
        for secret in {token, quote(token, safe="")}:
            sanitized = sanitized.replace(secret, "[redacted]")
        return sanitized
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for key, nested in value.items():
            rendered_key = str(key)
            if rendered_key.lower() in {"token", "request_url"}:
                continue
            safe_key = _redact_token(rendered_key, token)
            sanitized[str(safe_key)] = _redact_token(nested, token)
        return sanitized
    if isinstance(value, list):
        return [_redact_token(item, token) for item in value]
    return value


def lookup_ipinfo(ip: str, token: str | None) -> dict[str, object] | None:
    """Return credential-safe IPinfo Lite evidence, or ``None`` if unavailable."""

    if not token:
        return None
    canonical_ip = str(ipaddress.ip_address(ip))
    request_url = _IPINFO_REQUEST_URL.format(
        ip=quote(canonical_ip, safe=":"), token=quote(token, safe="")
    )
    try:
        response = httpx.get(request_url, timeout=10.0, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        # Transport exception text can include the credential-bearing request URL.
        return None
    if not isinstance(payload, Mapping):
        return None

    sanitized = _redact_token(payload, token)
    if not isinstance(sanitized, dict):
        return None
    result = dict(sanitized)
    result["source"] = "ipinfo"
    if "asn_name" not in result and isinstance(result.get("as_name"), str):
        result["asn_name"] = result["as_name"]
    if "asn_type" not in result and isinstance(result.get("type"), str):
        result["asn_type"] = result["type"]
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dataset_provenance(
    path: Path, expected_url: str | None = None
) -> tuple[str, str]:
    """Return verified cache provenance or reject an incomplete cache entry."""

    metadata_path = path.with_name(f"{path.name}.meta.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata_url = metadata.get("url")
        retrieved_at = metadata.get("retrieved_at")
        digest = metadata.get("sha256")
        byte_count = metadata.get("byte_count")
        if (
            not isinstance(metadata_url, str)
            or not metadata_url
            or (
                expected_url is not None
                and metadata_url != _safe_dataset_url(expected_url)
            )
            or not isinstance(retrieved_at, str)
            or not retrieved_at
            or not isinstance(digest, str)
            or digest != sha256_file(path)
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count != path.stat().st_size
        ):
            raise ValueError
        return retrieved_at, digest
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError("Dataset provenance is unavailable") from None


def _manifest_entry(
    source: str,
    status: str,
    *,
    retrieved_at: str | None = None,
    sha256: str | None = None,
    matches: list[str] | None = None,
    dataset_url: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "source": source,
        "status": status,
        "retrieved_at": retrieved_at,
        "sha256": sha256,
        "matches": list(matches or []),
        **SOURCE_CATALOG[source],
    }
    if dataset_url is not None:
        entry["dataset_url"] = dataset_url
    return entry


def _collect_network_source(
    ip: str,
    cache: DatasetCache,
    source: str,
    url: str,
    name: str,
    *,
    minimum_score: int | None = None,
) -> dict[str, object]:
    try:
        path = cache.get(url, name)
        networks = parse_network_list(path, minimum_score=minimum_score)
        if not networks:
            raise ValueError("Dataset contains no valid networks")
        retrieved_at, digest = _dataset_provenance(path, url)
        return _manifest_entry(
            source,
            "available",
            retrieved_at=retrieved_at,
            sha256=digest,
            matches=match_networks(ip, networks),
        )
    except Exception:
        return _manifest_entry(source, "unavailable")


def _sapics_asset_name(file_list: object, family: int) -> str:
    if not isinstance(file_list, Mapping) or not isinstance(file_list.get("files"), list):
        raise ValueError("sapics package file list is invalid")
    suffix = f"-ipv{family}.csv"
    candidates: list[str] = []
    for item in file_list["files"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].lstrip("/")
        if name.endswith(suffix) and not name.endswith(f"-ipv{family}-num.csv"):
            candidates.append(name)
    if len(candidates) != 1:
        raise ValueError("sapics package has no unambiguous address-family CSV")
    return candidates[0]


def _collect_sapics(
    ip: str, cache: DatasetCache
) -> tuple[dict[str, object], dict[str, object] | None]:
    version: str | None = None
    try:
        package_path = cache.get(SAPICS_PACKAGE_METADATA_URL, "sapics-package.json")
        package_metadata = json.loads(package_path.read_text(encoding="utf-8"))
        tags = package_metadata.get("tags") if isinstance(package_metadata, Mapping) else None
        version = tags.get("latest") if isinstance(tags, Mapping) else None
        if not isinstance(version, str) or not version:
            raise ValueError("sapics package version is unavailable")

        files_url = SAPICS_PACKAGE_FILES_URL.format(version=quote(version, safe="."))
        files_path = cache.get(files_url, f"sapics-{version}-files.json")
        file_list = json.loads(files_path.read_text(encoding="utf-8"))
        family = ipaddress.ip_address(ip).version
        asset = _sapics_asset_name(file_list, family)
        dataset_url = SAPICS_DATASET_URL.format(version=version, asset=asset)
        dataset_path = cache.get(dataset_url, f"sapics-{version}-ipv{family}.csv")
        record = lookup_sapics_asn(ip, dataset_path)
        retrieved_at, digest = _dataset_provenance(dataset_path, dataset_url)
        entry = _manifest_entry(
            "sapics",
            "available",
            retrieved_at=retrieved_at,
            sha256=digest,
            dataset_url=dataset_url,
        )
        entry["version"] = version
        entry["asset"] = asset
        return entry, record
    except Exception:
        entry = _manifest_entry("sapics", "unavailable")
        if version is not None:
            entry["version"] = version
        return entry, None


def _collect_ipinfo(
    ip: str, token: str | None
) -> tuple[dict[str, object], dict[str, object] | None]:
    if not token:
        return _manifest_entry("ipinfo", "unavailable"), None
    record = lookup_ipinfo(ip, token)
    if record is None:
        return _manifest_entry("ipinfo", "unavailable"), None
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (
        _manifest_entry(
            "ipinfo",
            "available",
            retrieved_at=_utc_now(),
            sha256=hashlib.sha256(canonical).hexdigest(),
        ),
        record,
    )


def collect_intelligence(
    ip: str, cache: DatasetCache, token: str | None
) -> dict[str, object]:
    """Collect isolated reputation and ASN sources for one canonical IP."""

    canonical_ip = str(ipaddress.ip_address(ip))
    manifest = [
        _collect_network_source(
            canonical_ip,
            cache,
            "ipsum",
            IPSUM_DATASET_URL,
            "ipsum.txt",
            minimum_score=3,
        ),
        _collect_network_source(
            canonical_ip,
            cache,
            "firehol_level1",
            FIREHOL_LEVEL1_DATASET_URL,
            "firehol_level1.netset",
        ),
        _collect_network_source(
            canonical_ip,
            cache,
            "firehol_level2",
            FIREHOL_LEVEL2_DATASET_URL,
            "firehol_level2.netset",
        ),
    ]

    sapics_entry, sapics_record = _collect_sapics(canonical_ip, cache)
    ipinfo_entry, ipinfo_record = _collect_ipinfo(canonical_ip, token)
    manifest.extend((sapics_entry, ipinfo_entry))
    signals = [record for record in (sapics_record, ipinfo_record) if record is not None]

    category_by_source = {
        "ipsum": "aggregated_abuse",
        "firehol_level1": "conservative_blocklist",
        "firehol_level2": "broader_blocklist",
    }
    high_confidence_matches = [
        reputation_match(
            canonical_ip,
            source=str(entry["source"]),
            network=network,
            category=category_by_source[str(entry["source"])],
        )
        for entry in manifest
        if entry["source"] in {"ipsum", "firehol_level1"}
        for network in entry["matches"]
    ]
    other_matches = [
        reputation_match(
            canonical_ip,
            source="firehol_level2",
            network=network,
            category=category_by_source["firehol_level2"],
        )
        for entry in manifest
        if entry["source"] == "firehol_level2"
        for network in entry["matches"]
    ]
    required_source_status = {
        str(entry["source"]): str(entry["status"])
        for entry in manifest
        if entry["source"] in category_by_source
    }
    return {
        "signals": signals,
        "high_confidence_matches": high_confidence_matches,
        "other_matches": other_matches,
        "required_source_status": required_source_status,
        "required_sources_available": all(
            required_source_status.get(source) == "available"
            for source in category_by_source
        ),
        "manifest": manifest,
        # Keep source results directly accessible to callers that do not emit a
        # separate manifest artifact.
        "sources": [dict(entry) for entry in manifest],
    }
