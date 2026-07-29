"""Strict request/response schemas for the Shop email phone-OTP check feature.

Every model forbids extra fields. Read models never expose the full email, the
CredentialStore reference, the email fingerprint, or any proxy secret — only a
masked value and visible result/phone metadata. The create payload's email text
is write-only and never echoed back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...schemas.common import Page, StrictModel


RunStatus = Literal[
    "queued",
    "preparing",
    "running",
    "completed",
    "completed_with_issues",
    "cancelled",
    "failed",
]
EmailResult = Literal[
    "phone_otp_required",
    "email_otp_required",
    "login_success",
    "account_not_found",
    "email_rejected",
    "captcha_or_challenge",
    "proxy_failed",
    "navigation_failed",
    "unknown",
    "cancelled",
]
EmailState = Literal["pending", "running", "terminal"]
WorkerState = Literal[
    "pending",
    "proxy_check",
    "profile_create",
    "launching",
    "processing",
    "stopping",
    "terminal",
]
PhoneConfidence = Literal["exact", "ambiguous", "unknown"]
CleanupState = Literal["none", "in_progress", "partial", "done"]

# Terminal results that may be re-attempted. Kept in one place so the API, the
# coordinator, and the UI agree on what "retryable" means.
RETRYABLE_RESULTS: frozenset[str] = frozenset(
    {"captcha_or_challenge", "proxy_failed", "navigation_failed", "unknown"}
)


class ShopCheckRunCreate(StrictModel):
    # Write-only: the pasted authorized-account list. Never echoed in any
    # response, log, or error. Bounded to keep a paste from exhausting memory.
    email_text: str = Field(
        min_length=1,
        max_length=2_000_000,
        json_schema_extra={"writeOnly": True},
    )
    emails_per_profile: int = Field(default=5, ge=1, le=5)
    max_parallel: int = Field(default=3, ge=1, le=5)
    # None => random region; otherwise a two-letter country code (e.g. "US").
    region: str | None = Field(default=None)
    profile_prefix: str | None = Field(default=None, max_length=80)
    output_dir: str | None = Field(default=None, max_length=500)
    # Hard authorization gate: the operator must affirm these accounts are their
    # own or explicitly authorized. The server rejects a run without it.
    authorized_only_ack: bool = Field(default=False)

    @field_validator("region")
    @classmethod
    def _valid_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError("region must be a two-letter country code")
        return code

    @model_validator(mode="after")
    def _require_authorization(self):
        if not self.authorized_only_ack:
            raise ValueError(
                "authorized_only_ack must be true: this workflow is for owned or "
                "explicitly authorized accounts only"
            )
        return self


class InvalidInputEntry(StrictModel):
    line: int = Field(ge=1)
    masked: str
    reason: str


class DuplicateInputEntry(StrictModel):
    line: int = Field(ge=1)
    masked: str


class InputSummary(StrictModel):
    total_lines: int = Field(ge=0)
    valid: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    invalid: int = Field(ge=0)
    worker_count: int = Field(ge=0)
    invalid_entries: list[InvalidInputEntry]
    duplicate_entries: list[DuplicateInputEntry]


class ShopCheckWorkerRead(StrictModel):
    id: str
    ordinal: int
    state: WorkerState
    profile_id: str | None
    proxy_id: str | None
    assigned_count: int
    processed_count: int
    error: str | None


class ShopCheckEmailRead(StrictModel):
    id: str
    ordinal: int
    # Masked rendering only — never the plaintext email, ref, or fingerprint.
    email_masked: str
    state: EmailState
    result: EmailResult | None
    retryable: bool
    phone_prefix: str | None
    phone_suffix: str | None
    phone_country_code: str | None
    phone_country_name: str | None
    phone_region_name: str | None
    phone_confidence: PhoneConfidence | None
    retry_count: int
    worker_id: str | None
    checked_at: datetime | None


class ShopCheckEmailPage(Page[ShopCheckEmailRead]):
    pass


class ShopCheckRunSummary(StrictModel):
    id: str
    status: RunStatus
    region: str | None
    emails_per_profile: int
    max_parallel: int
    target_url: str
    total_emails: int
    terminal_count: int
    retryable_count: int
    worker_count: int
    cleanup_state: CleanupState
    # Recomputed from item rows; keyed by result value.
    result_counts: dict[str, int]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ShopCheckRunPage(Page[ShopCheckRunSummary]):
    pass


class ShopCheckRunDetail(ShopCheckRunSummary):
    profile_prefix: str | None
    output_dir: str | None
    error: str | None
    workers: list[ShopCheckWorkerRead]


class ShopCheckRunCreateResult(StrictModel):
    run: ShopCheckRunDetail
    input_summary: InputSummary


class ShopCheckCleanupRequest(StrictModel):
    # Explicit confirmation. `confirm` must be exactly true, and the client echoes
    # the exact owned-profile count it saw; the server 409s on a mismatch so a
    # stale UI can never delete a different number than it displayed. The run id
    # comes from the path — never a client-supplied profile-id or path list.
    confirm: Literal[True]
    expected_profile_count: int = Field(ge=0)


class CleanupProfileResult(StrictModel):
    profile_id: str
    deleted: bool
    error: str | None


class ShopCheckCleanupResult(StrictModel):
    run_id: str
    cleanup_state: CleanupState
    requested: int
    deleted: int
    failed: int
    profiles: list[CleanupProfileResult]
