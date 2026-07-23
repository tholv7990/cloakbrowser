from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ...schemas.common import StrictModel


ProxyScheme = Literal["direct", "http", "https", "socks5", "socks5h"]


class ProxyWrite(StrictModel):
    label: str = Field(min_length=1, max_length=120)
    scheme: ProxyScheme
    host: str = Field(default="", max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=200, json_schema_extra={"writeOnly": True})
    password: str | None = Field(default=None, max_length=500, json_schema_extra={"writeOnly": True})
    clear_credentials: bool = False
    test_before_launch: bool = True

    @model_validator(mode="after")
    def validate_proxy(self):
        self.label = self.label.strip()
        self.host = self.host.strip().casefold()
        if not self.label:
            raise ValueError("label is required")
        supplied = self.username is not None or self.password is not None
        if supplied and (not self.username or not self.password):
            raise ValueError("username and password must be supplied together")
        if self.clear_credentials and supplied:
            raise ValueError("clear_credentials cannot accompany credentials")
        if self.scheme == "direct":
            if self.host or self.port is not None or supplied:
                raise ValueError("direct mode cannot have an endpoint or credentials")
        elif not self.host or self.port is None or any(c.isspace() for c in self.host):
            raise ValueError("proxy host and port are required")
        return self


class ProxyRead(StrictModel):
    id: str
    label: str
    scheme: ProxyScheme
    host: str
    port: int | None
    username: None = None
    has_password: bool
    masked_endpoint: str
    test_before_launch: bool
    assigned_profile_count: int
    exit_ip: str | None
    country: str | None
    city: str | None
    timezone: str | None
    asn: str | None
    organization: str | None
    proxy_type: str | None
    type_confidence: float | None
    reputation: str | None
    latency_ms: int | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProxyParseRequest(StrictModel):
    raw: str = Field(min_length=1, max_length=2000, json_schema_extra={"writeOnly": True})


class ParsedProxyRead(StrictModel):
    scheme: ProxyScheme
    host: str
    port: int | None
    username: str | None
    has_password: bool


class ProxyQuickTestRead(StrictModel):
    ok: bool
    connectivity: bool
    exit_ip: str | None
    exit_ip_matches: bool | None
    latency_ms: int | None
    country: str | None
    country_name: str | None
    city: str | None
    zip_code: str | None
    timezone: str | None
    latitude: float | None
    longitude: float | None
    asn: str | None
    organization: str | None
    checked_at: datetime
    error: str | None


class AlignmentFindingRead(StrictModel):
    status: Literal["aligned", "mismatch", "leak", "unknown"]
    detail: str


class ProxyQualityReportRead(StrictModel):
    id: str
    proxy_id: str
    state: Literal["queued", "running", "completed", "failed"]
    proxy_type: str | None
    type_confidence: float | None
    reputation: str | None
    matched_lists: list[str]
    google_outcome: str | None
    turnstile_outcome: str | None
    alignment: dict[str, AlignmentFindingRead]
    latency_ms: int | None
    exit_ip: str | None
    country: str | None
    city: str | None
    timezone: str | None
    asn: str | None
    organization: str | None
    screenshot_path: str | None
    report_path: str | None
    observed_scope: str
    checked_at: datetime
