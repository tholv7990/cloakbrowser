"""Pure, deterministic models used by the proxy-quality benchmark.

The functions in this module deliberately perform no I/O and never log input
values.  That keeps proxy credentials and other authentication material out of
benchmark artifacts.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Mapping
from urllib.parse import urlsplit


class NetworkType(str, Enum):
    """Classifications supported by the network evidence model."""

    MOBILE = "mobile"
    RESIDENTIAL_OR_ISP = "residential_or_isp"
    DATACENTER_OR_HOSTING = "datacenter_or_hosting"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    """Confidence assigned to a network classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Reputation(str, Enum):
    """Observed reputation level for a proxy run."""

    BLOCKED = "blocked"
    QUESTIONABLE = "questionable"
    CLEAN_OBSERVED = "clean_observed"
    UNKNOWN = "unknown"


class Suitability(str, Enum):
    """Whether a run supports using the proxy on protected sites."""

    YES = "yes"
    NO = "no"
    UNCERTAIN = "uncertain"


_HOSTING_TERMS = ("hosting", "cloud", "datacenter", "data center", "vps")
_STRUCTURED_HOSTING_VALUES = frozenset(
    {"hosting", "cloud", "datacenter", "data center", "data_center", "vps", "datacenter_or_hosting"}
)
_STRUCTURED_ISP_VALUES = frozenset({"isp", "residential", "residential_or_isp"})
_COLON_PROXY = re.compile(r"^(?P<host>.+):(?P<port>\d+):(?P<username>[^:]*):(?P<password>.*)$")


def _safe_scalar(value: object) -> str | int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return value
    return None


def _carrier_fields(signal: Mapping[str, object]) -> dict[str, str | int | float]:
    fields: dict[str, str | int | float] = {}
    carrier = signal.get("carrier")
    if isinstance(carrier, Mapping):
        for source_field, output_field in (("name", "carrier"), ("mcc", "mcc"), ("mnc", "mnc")):
            value = _safe_scalar(carrier.get(source_field))
            if value is not None:
                fields[output_field] = value
    else:
        value = _safe_scalar(carrier)
        if value is not None:
            fields["carrier"] = value
    for field in ("mcc", "mnc"):
        value = _safe_scalar(signal.get(field))
        if value is not None:
            fields[field] = value
    return fields


def _source_id(signal: dict[str, object], index: int) -> str:
    source = signal.get("source")
    if isinstance(source, str) and source.strip():
        return f"source:{source.strip()}"
    return f"signal:{index}"


def _is_mobile_signal(signal: dict[str, object]) -> bool:
    return signal.get("is_mobile") is True or bool(_carrier_fields(signal))


def _is_structured_hosting_signal(signal: dict[str, object]) -> bool:
    if any(signal.get(field) is True for field in ("is_hosting", "is_datacenter", "is_cloud")):
        return True
    for field in ("asn_type", "network_type", "type"):
        value = signal.get(field)
        if isinstance(value, str) and value.strip().lower() in _STRUCTURED_HOSTING_VALUES:
            return True
    return False


def _is_structured_isp_signal(signal: dict[str, object]) -> bool:
    if any(signal.get(field) is True for field in ("is_isp", "is_residential")):
        return True
    for field in ("asn_type", "network_type", "type"):
        value = signal.get(field)
        if isinstance(value, str) and value.strip().lower() in _STRUCTURED_ISP_VALUES:
            return True
    return False


def _has_hosting_name_heuristic(signal: dict[str, object]) -> bool:
    for field in ("organization", "org", "asn_name", "name"):
        value = signal.get(field)
        if isinstance(value, str) and any(term in value.lower() for term in _HOSTING_TERMS):
            return True
    return False


def _safe_classification_evidence(
    signal: dict[str, object], index: int, category: str
) -> dict[str, object]:
    source = signal.get("source")
    evidence: dict[str, object] = {
        "source": source.strip() if isinstance(source, str) and source.strip() else f"signal:{index}",
    }
    asn = signal.get("asn")
    if isinstance(asn, (str, int)) and not isinstance(asn, bool):
        evidence["asn"] = asn
    for field in ("organization", "org", "asn_name", "name"):
        organization = signal.get(field)
        if isinstance(organization, str) and organization.strip():
            evidence["organization"] = organization.strip()
            break
    evidence["category"] = category

    flags: dict[str, object] = {}
    for field in (
        "is_mobile",
        "is_hosting",
        "is_datacenter",
        "is_cloud",
        "is_isp",
        "is_residential",
    ):
        if isinstance(signal.get(field), bool):
            flags[field] = signal[field]
    for field in ("asn_type", "network_type", "type"):
        value = signal.get(field)
        if isinstance(value, str) and value.strip():
            flags[field] = value.strip()
    flags.update(_carrier_fields(signal))
    privacy = signal.get("privacy")
    if isinstance(privacy, Mapping):
        safe_privacy = {
            str(key): value
            for key, value in privacy.items()
            if isinstance(key, str) and key in {"vpn", "proxy", "tor", "relay"} and isinstance(value, bool)
        }
        if safe_privacy:
            flags["privacy"] = safe_privacy
    evidence["flags"] = flags
    return evidence


def classify_network(signals: list[dict[str, object]]) -> dict[str, object]:
    """Classify network evidence without network access or source weighting.

    A source contributes at most one vote to each classification.  Text in an
    ASN/organization name can indicate hosting only when no structured evidence
    supports that classification, and therefore remains low confidence.
    """

    mobile_sources: set[str] = set()
    isp_sources: set[str] = set()
    hosting_structured_sources: set[str] = set()
    hosting_heuristic_sources: set[str] = set()
    categories: list[str] = []

    for index, signal in enumerate(signals):
        source_id = _source_id(signal, index)
        mobile = _is_mobile_signal(signal)
        hosting = _is_structured_hosting_signal(signal)
        isp = _is_structured_isp_signal(signal) and not mobile
        heuristic_hosting = not hosting and _has_hosting_name_heuristic(signal)
        if mobile:
            mobile_sources.add(source_id)
        if isp:
            isp_sources.add(source_id)
        if hosting:
            hosting_structured_sources.add(source_id)
        elif heuristic_hosting:
            hosting_heuristic_sources.add(source_id)

        signal_categories = []
        if mobile:
            signal_categories.append(NetworkType.MOBILE.value)
        if isp:
            signal_categories.append(NetworkType.RESIDENTIAL_OR_ISP.value)
        if hosting or heuristic_hosting:
            signal_categories.append(NetworkType.DATACENTER_OR_HOSTING.value)
        categories.append(
            signal_categories[0]
            if len(signal_categories) == 1
            else ("conflict" if signal_categories else NetworkType.UNKNOWN.value)
        )

    # Name matches are a fallback only; they never offset structured evidence
    # from another source.
    has_structured_evidence = bool(mobile_sources or isp_sources or hosting_structured_sources)
    hosting_sources = (
        hosting_structured_sources
        if hosting_structured_sources
        else (set() if has_structured_evidence else hosting_heuristic_sources)
    )
    ordered_types = (
        NetworkType.MOBILE.value,
        NetworkType.RESIDENTIAL_OR_ISP.value,
        NetworkType.DATACENTER_OR_HOSTING.value,
    )
    conflict_presence = {
        NetworkType.MOBILE.value: bool(mobile_sources),
        NetworkType.RESIDENTIAL_OR_ISP.value: bool(isp_sources),
        NetworkType.DATACENTER_OR_HOSTING.value: bool(
            hosting_structured_sources or hosting_heuristic_sources
        ),
    }
    conflicts = [network_type for network_type in ordered_types if conflict_presence[network_type]]
    if len(conflicts) < 2:
        conflicts = []

    votes = {
        NetworkType.MOBILE.value: len(mobile_sources),
        NetworkType.RESIDENTIAL_OR_ISP.value: len(isp_sources),
        NetworkType.DATACENTER_OR_HOSTING.value: len(hosting_sources),
    }
    top_count = max(votes.values(), default=0)
    winners = [network_type for network_type in ordered_types if votes[network_type] == top_count and top_count]
    network_type = winners[0] if len(winners) == 1 else NetworkType.UNKNOWN.value
    if network_type == NetworkType.UNKNOWN.value:
        confidence = Confidence.LOW
    elif conflicts:
        confidence = Confidence.LOW
    elif network_type == NetworkType.DATACENTER_OR_HOSTING.value and not hosting_structured_sources:
        confidence = Confidence.LOW
    else:
        confidence = Confidence.HIGH if top_count >= 2 else Confidence.MEDIUM

    evidence = [
        _safe_classification_evidence(signal, index, categories[index])
        for index, signal in enumerate(signals)
    ]
    return {
        "type": network_type,
        "type_confidence": confidence.value,
        "conflicts": conflicts,
        "evidence": evidence,
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _site_verdict(site_outcomes: Mapping[str, object], site: str) -> object:
    value = site_outcomes.get(site)
    if isinstance(value, Mapping):
        return value.get("verdict")
    return value


def summarize_report(report: dict[str, object]) -> dict[str, object]:
    """Return a concise reputation and suitability result from live evidence."""

    connectivity = _mapping(report.get("connectivity"))
    reputation_intelligence = _mapping(report.get("reputation_intelligence"))
    identity_alignment = _mapping(report.get("identity_alignment"))
    site_outcomes = _mapping(report.get("site_outcomes"))
    classification = _mapping(report.get("classification"))

    high_matches = reputation_intelligence.get("high_confidence_matches")
    other_matches = reputation_intelligence.get("other_matches")
    required_sources_available = reputation_intelligence.get("required_sources_available") is True
    exit_ip_agreement = connectivity.get("exit_ip_agreement") is True
    identity_field_matches = [
        _mapping(identity_alignment.get(field)).get("matches")
        for field in ("http_exit_ip", "webrtc", "timezone", "locale", "dns")
    ]
    identity_aligned = (
        identity_alignment.get("status") == "aligned"
        and identity_alignment.get("aligned") is True
        and identity_alignment.get("complete") is True
        and all(value is True for value in identity_field_matches)
    )
    identity_mismatch = (
        identity_alignment.get("status") == "mismatch"
        or identity_alignment.get("aligned") is False
        or any(value is False for value in identity_field_matches)
    )
    cloudflare = _site_verdict(site_outcomes, "cloudflare")
    google = _site_verdict(site_outcomes, "google")
    all_required_checks_pass = (
        connectivity.get("success") is True
        and exit_ip_agreement
        and not high_matches
        and not other_matches
        and required_sources_available
        and identity_aligned
        and cloudflare == "passed"
        and google in {"passed", "results"}
    )

    if google in {"captcha", "blocked"} or cloudflare in {"interactive", "blocked"} or high_matches:
        reputation = Reputation.BLOCKED
    elif other_matches or not exit_ip_agreement or identity_mismatch:
        reputation = Reputation.QUESTIONABLE
    elif all_required_checks_pass:
        reputation = Reputation.CLEAN_OBSERVED
    else:
        reputation = Reputation.UNKNOWN

    suitability = {
        Reputation.CLEAN_OBSERVED: Suitability.YES,
        Reputation.BLOCKED: Suitability.NO,
    }.get(reputation, Suitability.UNCERTAIN)
    summary: dict[str, object] = {
        "type": classification.get("type", NetworkType.UNKNOWN.value),
        "type_confidence": classification.get("type_confidence", Confidence.LOW.value),
        "reputation": reputation.value,
        "suitable_for_protected_sites": suitability.value,
    }
    if reputation is Reputation.CLEAN_OBSERVED:
        summary["observation_scope"] = {
            "timestamp_utc": report.get("timestamp_utc"),
            "sites": ["cloudflare_turnstile_demo", "google_search"],
        }
    return summary


def redact_proxy(proxy: str) -> str:
    """Redact credentials from a proxy URI or ``host:port:user:password`` value."""

    try:
        parsed = urlsplit(proxy)
        port = parsed.port
    except (TypeError, ValueError):
        return "<redacted-proxy>" if isinstance(proxy, str) and "@" in proxy else str(proxy)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname
        has_credentials = parsed.username is not None or parsed.password is not None or "@" in parsed.netloc
        if not host:
            return "<redacted-proxy>" if has_credentials else proxy
        rendered_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        if port is not None:
            rendered_host = f"{rendered_host}:{port}"
        if has_credentials:
            raw_userinfo = parsed.netloc.rpartition("@")[0]
            replacement = "***:***" if ":" in raw_userinfo or parsed.password is not None else "***"
            return f"{parsed.scheme}://{replacement}@{rendered_host}"
        return f"{parsed.scheme}://{rendered_host}"

    colon_match = _COLON_PROXY.match(proxy)
    if colon_match:
        return f"{colon_match.group('host')}:{colon_match.group('port')}:***:***"
    return proxy


def assert_no_secrets(value: object, secrets: set[str]) -> None:
    """Raise when a known secret occurs anywhere in supported nested values.

    The routine intentionally does not stringify arbitrary objects: converting
    them could itself serialize a credential through a custom ``__repr__``.
    """

    active_secrets = {secret for secret in secrets if secret}
    if not active_secrets:
        return

    seen: set[int] = set()

    def visit(candidate: object) -> None:
        if isinstance(candidate, str):
            if any(secret in candidate for secret in active_secrets):
                raise ValueError("secret found in value")
            return
        if isinstance(candidate, Mapping):
            candidate_id = id(candidate)
            if candidate_id in seen:
                return
            seen.add(candidate_id)
            for key, nested_value in candidate.items():
                visit(key)
                visit(nested_value)
            return
        if isinstance(candidate, (list, tuple, set, frozenset)):
            candidate_id = id(candidate)
            if candidate_id in seen:
                return
            seen.add(candidate_id)
            for nested_value in candidate:
                visit(nested_value)

    visit(value)
