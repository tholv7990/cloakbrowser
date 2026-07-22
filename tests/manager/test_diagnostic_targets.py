from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from manager_backend.features.diagnostics.schemas import bounded_findings
from manager_backend.features.diagnostics.targets import (
    TargetSnapshot,
    normalize_cloudflare,
    normalize_google_search,
    normalize_iphey,
    normalize_pixelscan,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "diagnostics"


class _FixtureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.page_loaded = False
        self.labels: dict[str, object] = {}
        self.signals: dict[str, object] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "main" and values.get("data-page-loaded") == "true":
            self.page_loaded = True
        label = values.get("data-diagnostic-label")
        if label is not None:
            self.labels[label] = values.get("data-value", "")
        signal = values.get("data-diagnostic-signal")
        if signal is not None:
            self.signals[signal] = values.get("data-value") == "true"


def _snapshot(name: str) -> TargetSnapshot:
    parser = _FixtureParser()
    parser.feed((FIXTURES / name).read_text(encoding="utf-8"))
    return TargetSnapshot(
        page_loaded=parser.page_loaded,
        labels=parser.labels,
        signals=parser.signals,
    )


@pytest.mark.parametrize(
    ("fixture", "status"),
    [
        ("pixelscan_pass.html", "passed"),
        ("pixelscan_warning.html", "warning"),
        ("pixelscan_failure.html", "failed"),
    ],
)
def test_pixelscan_normalizes_all_allowlisted_sections(fixture: str, status: str):
    result = normalize_pixelscan(_snapshot(fixture))

    assert result.status == status
    assert set(result.findings) == {
        "consistency",
        "automation",
        "browser",
        "hardware",
        "location",
        "overall_result",
    }
    assert bounded_findings("pixelscan", result.findings) == result.findings
    assert result.error_code is None


def test_pixelscan_layout_drift_is_a_bounded_warning_not_a_guessed_pass():
    result = normalize_pixelscan(_snapshot("pixelscan_layout_drift.html"))

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings["hardware"] == "unknown"
    assert result.findings["overall_result"] == "unknown"


@pytest.mark.parametrize(
    ("fixture", "status"),
    [
        ("iphey_pass.html", "passed"),
        ("iphey_warning.html", "warning"),
        ("iphey_failure.html", "failed"),
    ],
)
def test_iphey_normalizes_all_allowlisted_sections(fixture: str, status: str):
    result = normalize_iphey(_snapshot(fixture))

    assert result.status == status
    assert set(result.findings) == {"browser", "location", "hardware", "privacy"}
    assert bounded_findings("iphey", result.findings) == result.findings
    assert result.error_code is None


def test_iphey_layout_drift_is_a_bounded_warning_not_a_guessed_pass():
    result = normalize_iphey(_snapshot("iphey_layout_drift.html"))

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings["privacy"] == "unknown"


def test_cloudflare_loaded_page_without_challenge_passes():
    result = normalize_cloudflare(_snapshot("cloudflare_pass.html"))

    assert result.status == "passed"
    assert result.error_code is None
    assert result.findings == {
        "page_loaded": True,
        "managed_challenge": False,
        "user_interaction_required": False,
    }


def test_cloudflare_managed_challenge_pauses_for_user_and_never_passes():
    result = normalize_cloudflare(_snapshot("cloudflare_challenge.html"))

    assert result.status == "warning"
    assert result.error_code == "captcha_user_action_required"
    assert result.findings == {
        "page_loaded": True,
        "managed_challenge": True,
        "user_interaction_required": True,
    }


def test_cloudflare_layout_drift_is_warning():
    result = normalize_cloudflare(_snapshot("cloudflare_layout_drift.html"))

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings["page_loaded"] is True


def test_google_visible_results_pass():
    result = normalize_google_search(_snapshot("google_results.html"))

    assert result.status == "passed"
    assert result.error_code is None
    assert result.findings == {
        "page_loaded": True,
        "consent_interstitial": False,
        "captcha_detected": False,
        "results_visible": True,
    }


def test_google_consent_interstitial_is_warning_without_guessing_results():
    result = normalize_google_search(_snapshot("google_consent.html"))

    assert result.status == "warning"
    assert result.error_code is None
    assert result.findings["consent_interstitial"] is True
    assert result.findings["results_visible"] is False


def test_google_unusual_traffic_captcha_pauses_for_user():
    result = normalize_google_search(_snapshot("google_captcha.html"))

    assert result.status == "warning"
    assert result.error_code == "captcha_user_action_required"
    assert result.findings["captcha_detected"] is True
    assert result.findings["results_visible"] is False


def test_google_layout_drift_is_warning_not_a_guessed_pass():
    result = normalize_google_search(_snapshot("google_layout_drift.html"))

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings["results_visible"] is False


@pytest.mark.parametrize(
    ("normalizer", "kind", "expected_keys"),
    [
        (
            normalize_pixelscan,
            "pixelscan",
            {"consistency", "automation", "browser", "hardware", "location", "overall_result"},
        ),
        (normalize_iphey, "iphey", {"browser", "location", "hardware", "privacy"}),
        (
            normalize_cloudflare,
            "cloudflare",
            {"page_loaded", "managed_challenge", "user_interaction_required"},
        ),
        (
            normalize_google_search,
            "google_search",
            {"page_loaded", "consent_interstitial", "captcha_detected", "results_visible"},
        ),
    ],
)
def test_normalizers_emit_only_strict_bounded_keys(
    normalizer, kind: str, expected_keys: set[str]
):
    snapshot = TargetSnapshot(
        page_loaded=True,
        labels={
            "consistency": "passed",
            "automation": "not_detected",
            "browser": "aligned",
            "hardware": "aligned",
            "location": "aligned",
            "privacy": "passed",
            "overall_result": "passed",
            "secret": "password=should-not-escape",
            "oversized": "x" * 100_000,
        },
        signals={
            "managed_challenge": False,
            "user_interaction_required": False,
            "consent_interstitial": False,
            "captcha_detected": False,
            "results_visible": True,
            "secret": True,
        },
    )

    result = normalizer(snapshot)

    assert set(result.findings) == expected_keys
    assert bounded_findings(kind, result.findings) == result.findings
    assert len(str(result.findings)) < 512
    assert "secret" not in str(result.findings)
    assert "should-not-escape" not in str(result.findings)


def test_oversized_allowlisted_text_becomes_unknown_layout_warning():
    snapshot = TargetSnapshot(
        page_loaded=True,
        labels={
            "consistency": "passed",
            "automation": "not_detected",
            "browser": "aligned",
            "hardware": "x" * 10_000,
            "location": "aligned",
            "overall_result": "passed",
        },
    )

    result = normalize_pixelscan(snapshot)

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings["hardware"] == "unknown"


@pytest.mark.parametrize(
    ("normalizer", "labels", "section", "misplaced_value"),
    [
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "consistency",
            "aligned",
        ),
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "automation",
            "aligned",
        ),
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "browser",
            "not_detected",
        ),
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "hardware",
            "passed",
        ),
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "location",
            "not_detected",
        ),
        (
            normalize_pixelscan,
            {
                "consistency": "passed",
                "automation": "not_detected",
                "browser": "aligned",
                "hardware": "aligned",
                "location": "aligned",
                "overall_result": "passed",
            },
            "overall_result",
            "aligned",
        ),
        (
            normalize_iphey,
            {
                "browser": "passed",
                "location": "aligned",
                "hardware": "aligned",
                "privacy": "passed",
            },
            "browser",
            "not_detected",
        ),
        (
            normalize_iphey,
            {
                "browser": "passed",
                "location": "aligned",
                "hardware": "aligned",
                "privacy": "passed",
            },
            "location",
            "passed",
        ),
        (
            normalize_iphey,
            {
                "browser": "passed",
                "location": "aligned",
                "hardware": "aligned",
                "privacy": "passed",
            },
            "hardware",
            "not_detected",
        ),
        (
            normalize_iphey,
            {
                "browser": "passed",
                "location": "aligned",
                "hardware": "aligned",
                "privacy": "passed",
            },
            "privacy",
            "aligned",
        ),
    ],
)
def test_cross_section_labels_are_layout_drift_not_guessed_pass(
    normalizer, labels: dict[str, object], section: str, misplaced_value: str
):
    adversarial = dict(labels)
    adversarial[section] = misplaced_value

    result = normalizer(TargetSnapshot(page_loaded=True, labels=adversarial))

    assert result.status == "warning"
    assert result.error_code == "target_layout_changed"
    assert result.findings[section] == "unknown"


@pytest.mark.parametrize(
    ("section", "value", "status"),
    [
        ("consistency", "warning", "warning"),
        ("automation", "detected", "failed"),
        ("browser", "mismatch", "warning"),
        ("hardware", "mismatch", "warning"),
        ("location", "mismatch", "warning"),
        ("overall_result", "failed", "failed"),
    ],
)
def test_pixelscan_uses_section_specific_severity(
    section: str, value: str, status: str
):
    labels = {
        "consistency": "passed",
        "automation": "not_detected",
        "browser": "aligned",
        "hardware": "aligned",
        "location": "aligned",
        "overall_result": "passed",
    }
    labels[section] = value

    result = normalize_pixelscan(TargetSnapshot(page_loaded=True, labels=labels))

    assert result.status == status
    assert result.error_code is None


@pytest.mark.parametrize(
    ("section", "value", "status"),
    [
        ("browser", "warning", "warning"),
        ("browser", "failed", "failed"),
        ("location", "mismatch", "warning"),
        ("location", "failed", "failed"),
        ("hardware", "mismatch", "warning"),
        ("hardware", "failed", "failed"),
        ("privacy", "warning", "warning"),
        ("privacy", "failed", "failed"),
    ],
)
def test_iphey_uses_section_specific_severity(
    section: str, value: str, status: str
):
    labels = {
        "browser": "passed",
        "location": "aligned",
        "hardware": "aligned",
        "privacy": "passed",
    }
    labels[section] = value

    result = normalize_iphey(TargetSnapshot(page_loaded=True, labels=labels))

    assert result.status == status
    assert result.error_code is None


@pytest.mark.parametrize(
    "signals",
    [
        {"managed_challenge": True, "user_interaction_required": True},
        {"managed_challenge": False, "user_interaction_required": True},
    ],
)
def test_cloudflare_challenge_takes_priority_over_page_load_failure(signals):
    result = normalize_cloudflare(
        TargetSnapshot(page_loaded=False, signals=signals)
    )

    assert result.status == "warning"
    assert result.error_code == "captcha_user_action_required"
    assert result.findings["page_loaded"] is False


@pytest.mark.parametrize(
    "signals",
    [
        {"captcha_detected": True},
        {"unusual_traffic": True},
    ],
)
def test_google_captcha_takes_priority_over_page_load_failure(signals):
    result = normalize_google_search(
        TargetSnapshot(page_loaded=False, signals=signals)
    )

    assert result.status == "warning"
    assert result.error_code == "captcha_user_action_required"
    assert result.findings["page_loaded"] is False
    assert result.findings["captcha_detected"] is True


@pytest.mark.parametrize(
    "normalizer",
    [normalize_pixelscan, normalize_iphey, normalize_cloudflare, normalize_google_search],
)
def test_page_load_failure_is_a_bounded_failure(normalizer):
    result = normalizer(TargetSnapshot(page_loaded=False))

    assert result.status == "failed"
    assert result.error_code == "diagnostic_failed"
    assert len(str(result.findings)) < 512
