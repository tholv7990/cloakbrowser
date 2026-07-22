from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ...schemas.common import StrictModel


StepType = Literal["goto", "click", "fill", "select", "wait_url"]


class AutomationSelector(StrictModel):
    css: str | None = None
    id: str | None = None
    name: str | None = None
    role: str | None = None
    accessible_name: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    text: str | None = None
    testid: str | None = None


class AutomationStep(StrictModel):
    type: StepType
    url: str | None = None
    url_pattern: str | None = None
    success_url_pattern: str | None = None
    selectors: list[AutomationSelector] | None = None
    value: str | None = None
    variable: str | None = None


class TemplateWrite(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    steps: list[AutomationStep] = Field(default_factory=list)


class AutomationTemplateRead(StrictModel):
    id: str
    name: str
    description: str
    steps: list[AutomationStep]
    variables: list[str]
    created_at: datetime
    updated_at: datetime


class RecordingCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    profile_id: str
    description: str = Field(default="", max_length=500)


class AutomationRecordingRead(StrictModel):
    id: str
    name: str
    description: str
    profile_id: str
    status: Literal["recording", "stopped", "cancelled"]
    step_count: int
    template_id: str | None
    created_at: datetime


class AutomationRunItemRead(StrictModel):
    profile_id: str
    profile_name: str
    status: Literal["pending", "running", "attention", "completed", "failed", "cancelled"]
    current_step: int
    total_steps: int
    last_completed_step: int
    message: str | None
    attention_reason: str | None
    error: str | None


class AutomationRunRead(StrictModel):
    id: str
    template_id: str
    template_name: str
    status: Literal["running", "completed", "failed", "cancelled"]
    max_parallel: int
    total: int
    completed_count: int
    failed_count: int
    attention_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    items: list[AutomationRunItemRead]


class RunAssignment(StrictModel):
    profile_id: str
    variables: dict[str, str] = Field(default_factory=dict)
    credential_id: str | None = None


class StartRunPayload(StrictModel):
    assignments: list[RunAssignment] = Field(min_length=1)
    max_parallel: int = Field(default=1, ge=1, le=5)


class CredentialPoolSummary(StrictModel):
    available: int
    reserved: int
    used: int
    failed: int
    total: int


class CredentialImport(StrictModel):
    text: str = Field(min_length=1, max_length=200_000, json_schema_extra={"writeOnly": True})


class ProfileFactoryItemRead(StrictModel):
    id: str
    profile_id: str | None
    status: str
    message: str | None


class ProfileFactoryJobRead(StrictModel):
    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    quantity: int
    name_prefix: str
    automation_template_id: str | None
    start_automation: bool
    created_count: int
    failed_count: int
    items: list[ProfileFactoryItemRead]
    created_at: datetime


class StartFactoryPayload(StrictModel):
    quantity: int = Field(ge=1, le=50)
    name_prefix: str = Field(min_length=1, max_length=120)
    automation_template_id: str | None = None
    start_automation: bool = False
