from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from ...schemas.common import Page, StrictModel


DiagnosticKind = Literal[
    "direct_google_control",
    "pixelscan",
    "iphey",
    "cloudflare",
    "google_search",
]
DiagnosticStatus = Literal[
    "queued", "running", "passed", "warning", "failed", "cancelled"
]
DiagnosticTargetUrl = Literal[
    "https://www.google.com/search?q=CloakBrowser+diagnostic",
    "https://pixelscan.net/",
    "https://iphey.com/",
    "https://challenge.cloudflare.com/turnstile/v0/generic/",
    "https://www.google.com/search?q=CloakBrowser+browser+diagnostic",
]
TARGET_URLS: dict[DiagnosticKind, DiagnosticTargetUrl] = {
    "direct_google_control": "https://www.google.com/search?q=CloakBrowser+diagnostic",
    "pixelscan": "https://pixelscan.net/",
    "iphey": "https://iphey.com/",
    "cloudflare": "https://challenge.cloudflare.com/turnstile/v0/generic/",
    "google_search": "https://www.google.com/search?q=CloakBrowser+browser+diagnostic",
}
DiagnosticSummary = Literal[
    "Diagnostic completed.",
    "Diagnostic completed with warnings.",
    "Diagnostic failed.",
    "Diagnostic cancelled.",
]
DiagnosticErrorMessage = Literal[
    "The diagnostic could not be completed.",
    "The manager restarted before the diagnostic completed.",
    "The diagnostic could not be scheduled.",
    "The browser closed before the diagnostic completed.",
    "Stop the profile before running this diagnostic.",
    "The assigned proxy is unavailable.",
    "The diagnostic target could not be reached.",
    "The diagnostic did not complete before its time limit.",
    "The diagnostic target could not be read reliably.",
    "The target requires user interaction.",
]
DiagnosticErrorCode = Literal[
    "diagnostic_failed",
    "manager_restarted",
    "scheduler_unavailable",
    "browser_crashed",
    "profile_not_stopped",
    "proxy_preflight_failed",
    "network_error",
    "timeout",
    "target_layout_changed",
    "captcha_user_action_required",
]
FindingLabel = Literal[
    "passed",
    "warning",
    "failed",
    "unknown",
    "aligned",
    "mismatch",
    "detected",
    "not_detected",
    "loaded",
    "not_loaded",
    "visible",
    "not_visible",
    "required",
    "not_required",
]
FindingValue = StrictBool | FindingLabel


FINDING_SHAPES: dict[str, dict[str, Literal["bool", "label"]]] = {
    "direct_google_control": {
        "page_loaded": "bool",
        "consent_interstitial": "bool",
        "captcha_detected": "bool",
        "results_visible": "bool",
    },
    "google_search": {
        "page_loaded": "bool",
        "consent_interstitial": "bool",
        "captcha_detected": "bool",
        "results_visible": "bool",
    },
    "pixelscan": {
        "consistency": "label",
        "automation": "label",
        "browser": "label",
        "hardware": "label",
        "location": "label",
        "overall_result": "label",
    },
    "iphey": {
        "browser": "label",
        "location": "label",
        "hardware": "label",
        "privacy": "label",
    },
    "cloudflare": {
        "page_loaded": "bool",
        "managed_challenge": "bool",
        "user_interaction_required": "bool",
    },
}
FINDING_LABELS = frozenset(
    {
        "passed",
        "warning",
        "failed",
        "unknown",
        "aligned",
        "mismatch",
        "detected",
        "not_detected",
        "loaded",
        "not_loaded",
        "visible",
        "not_visible",
        "required",
        "not_required",
    }
)


def bounded_findings(kind: str, value: object) -> dict[str, FindingValue]:
    if not isinstance(value, dict):
        return {}
    shape = FINDING_SHAPES.get(kind, {})
    bounded: dict[str, FindingValue] = {}
    for key, item in value.items():
        expected = shape.get(key)
        if expected == "bool" and isinstance(item, bool):
            bounded[key] = item
        elif expected == "label" and isinstance(item, str) and item in FINDING_LABELS:
            bounded[key] = item  # type: ignore[assignment]
    return bounded


class ProfileDiagnosticRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=36)


class DiagnosticRead(StrictModel):
    id: str
    profile_id: str | None
    kind: DiagnosticKind
    status: DiagnosticStatus
    target_url: DiagnosticTargetUrl
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: int = Field(ge=0, le=100)
    summary: DiagnosticSummary | None
    findings: dict[str, FindingValue]
    screenshot_path: str | None
    report_path: str | None
    error_code: DiagnosticErrorCode | None
    error_message: DiagnosticErrorMessage | None


class DiagnosticPage(Page[DiagnosticRead]):
    pass


class DiagnosticResultUpdate(StrictModel):
    kind: DiagnosticKind
    status: Literal["passed", "warning", "failed"]
    findings: dict[str, FindingValue] = Field(default_factory=dict, max_length=6)
    error_code: DiagnosticErrorCode | None = None
    screenshot_path: str | None = Field(default=None, max_length=2048)
    report_path: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_bounded_result(self):
        if bounded_findings(self.kind, self.findings) != self.findings:
            raise ValueError("findings do not match the diagnostic result schema")
        if self.status == "passed" and self.error_code is not None:
            raise ValueError("passed diagnostics cannot include an error")
        if self.status == "warning" and self.error_code not in {
            None,
            "target_layout_changed",
            "captcha_user_action_required",
        }:
            raise ValueError("warning diagnostics use warning error codes")
        if self.status == "failed" and self.error_code == "captcha_user_action_required":
            raise ValueError("CAPTCHA action-required is a warning result")
        return self
