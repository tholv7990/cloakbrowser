from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .runner import TargetResult


_MAX_SNAPSHOT_ITEMS = 16
_MAX_VISIBLE_LABEL_CHARS = 64
_PIXELSCAN_SEMANTICS = {
    "consistency": {"passed": "pass", "warning": "warn", "failed": "fail"},
    "automation": {"not_detected": "pass", "detected": "fail"},
    "browser": {"aligned": "pass", "mismatch": "warn"},
    "hardware": {"aligned": "pass", "mismatch": "warn"},
    "location": {"aligned": "pass", "mismatch": "warn"},
    "overall_result": {
        "passed": "pass",
        "warning": "warn",
        "failed": "fail",
    },
}
_IPHEY_SEMANTICS = {
    "browser": {"passed": "pass", "warning": "warn", "failed": "fail"},
    "location": {"aligned": "pass", "mismatch": "warn", "failed": "fail"},
    "hardware": {"aligned": "pass", "mismatch": "warn", "failed": "fail"},
    "privacy": {"passed": "pass", "warning": "warn", "failed": "fail"},
}


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """A bounded, pre-extracted view of visible diagnostic page state.

    Browser adapters should populate only the target's allowlisted labels and
    boolean signals. Raw DOM, arbitrary page text, cookies, storage, and
    response bodies do not belong at this boundary.
    """

    page_loaded: bool
    labels: Mapping[str, object] = field(default_factory=dict)
    signals: Mapping[str, object] = field(default_factory=dict)


def _safe_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict) or len(value) > _MAX_SNAPSHOT_ITEMS:
        return {}
    return value


def _visible_label(
    labels: Mapping[str, object], key: str, semantics: Mapping[str, str]
) -> tuple[str, str | None]:
    value = labels.get(key)
    if not isinstance(value, str) or len(value) > _MAX_VISIBLE_LABEL_CHARS:
        return "unknown", None
    normalized = "_".join(value.strip().casefold().replace("-", " ").split())
    severity = semantics.get(normalized)
    if severity is None:
        return "unknown", None
    return normalized, severity


def _visible_bool(signals: Mapping[str, object], key: str) -> bool | None:
    value = signals.get(key)
    return value if isinstance(value, bool) else None


def _label_result(
    snapshot: TargetSnapshot, section_semantics: Mapping[str, Mapping[str, str]]
) -> TargetResult:
    labels = _safe_mapping(snapshot.labels)
    normalized = {
        key: _visible_label(labels, key, semantics)
        for key, semantics in section_semantics.items()
    }
    findings = {key: value for key, (value, _severity) in normalized.items()}
    severities = [severity for _value, severity in normalized.values()]
    if snapshot.page_loaded is not True:
        return TargetResult(
            status="failed",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="diagnostic_failed",
        )
    if None in severities:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="target_layout_changed",
        )
    if "fail" in severities:
        status = "failed"
    elif "warn" in severities:
        status = "warning"
    else:
        status = "passed"
    return TargetResult(
        status=status,
        findings=findings,
        final_url="",
        title="",
        screenshot=None,
    )


def normalize_pixelscan(snapshot: TargetSnapshot) -> TargetResult:
    """Normalize only Pixelscan's six allowlisted visible result labels."""

    return _label_result(snapshot, _PIXELSCAN_SEMANTICS)


def normalize_iphey(snapshot: TargetSnapshot) -> TargetResult:
    """Normalize only IPhey's four allowlisted visible result labels."""

    return _label_result(snapshot, _IPHEY_SEMANTICS)


def normalize_cloudflare(snapshot: TargetSnapshot) -> TargetResult:
    """Normalize Cloudflare state and stop at any managed challenge."""

    signals = _safe_mapping(snapshot.signals)
    loaded = snapshot.page_loaded is True
    challenge = _visible_bool(signals, "managed_challenge")
    interaction = _visible_bool(signals, "user_interaction_required")
    findings = {
        "page_loaded": loaded,
        "managed_challenge": challenge is True,
        "user_interaction_required": interaction is True or challenge is True,
    }
    if challenge is True or interaction is True:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="captcha_user_action_required",
        )
    if not loaded:
        return TargetResult(
            status="failed",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="diagnostic_failed",
        )
    if challenge is None or interaction is None:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="target_layout_changed",
        )
    return TargetResult(
        status="passed",
        findings=findings,
        final_url="",
        title="",
        screenshot=None,
    )


def normalize_google_search(snapshot: TargetSnapshot) -> TargetResult:
    """Normalize Google Search state without interacting with interstitials."""

    signals = _safe_mapping(snapshot.signals)
    loaded = snapshot.page_loaded is True
    consent = _visible_bool(signals, "consent_interstitial")
    captcha = _visible_bool(signals, "captcha_detected")
    unusual_traffic = _visible_bool(signals, "unusual_traffic")
    results = _visible_bool(signals, "results_visible")
    captcha_detected = captcha is True or unusual_traffic is True
    findings = {
        "page_loaded": loaded,
        "consent_interstitial": consent is True,
        "captcha_detected": captcha_detected,
        "results_visible": results is True,
    }
    if captcha_detected:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="captcha_user_action_required",
        )
    if not loaded:
        return TargetResult(
            status="failed",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="diagnostic_failed",
        )
    if consent is True:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
        )
    if consent is None or results is None or (captcha is None and unusual_traffic is None):
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="target_layout_changed",
        )
    if results is not True:
        return TargetResult(
            status="warning",
            findings=findings,
            final_url="",
            title="",
            screenshot=None,
            error_code="target_layout_changed",
        )
    return TargetResult(
        status="passed",
        findings=findings,
        final_url="",
        title="",
        screenshot=None,
    )
