from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ...schemas.common import StrictModel


StepType = Literal["goto", "click", "fill", "select", "wait_url"]

# Website credentials are never literals or public inputs: they are pooled and
# resolved from the secure CredentialStore. Only these variable names are treated
# as credential references; any other name that could smuggle a secret through a
# public field is rejected outright.
CREDENTIAL_VARIABLES = frozenset({"email", "password"})
_SECRET_SUBSTRINGS = (
    "pass", "token", "secret", "cookie", "apikey", "authorization", "credential", "otp",
)


def is_credential_variable(name: str) -> bool:
    return name.strip().lower() in CREDENTIAL_VARIABLES


def is_secret_variable_name(name: str) -> bool:
    """True if `name` could carry a secret (and is not a recognized credential ref)."""
    if is_credential_variable(name):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(token in normalized for token in _SECRET_SUBSTRINGS)


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

    @model_validator(mode="after")
    def _no_literal_secrets(self):
        if self.type == "fill":
            # A fill types text into an input — the classic credential sink. It must
            # reference a declared variable, never a literal value.
            if self.value is not None:
                raise ValueError("fill steps must reference a variable, not a literal value")
            if not (self.variable and self.variable.strip()):
                raise ValueError("fill steps require a variable reference")
        if self.variable is not None:
            if not self.variable.strip():
                raise ValueError("variable must not be blank")
            if is_secret_variable_name(self.variable):
                raise ValueError("variable name may not carry a secret")
        return self


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

    @model_validator(mode="after")
    def _public_variables_only(self):
        # Credentials come from the pool; the request carries public inputs only.
        for key in self.variables:
            if is_credential_variable(key) or is_secret_variable_name(key):
                raise ValueError("credential/secret variables come from the pool, not the request")
        return self


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


