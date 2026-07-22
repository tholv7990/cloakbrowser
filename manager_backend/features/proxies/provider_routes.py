from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from ...schemas.common import StrictModel
from .providers import generate_and_store, list_providers, save_provider_credentials


ProviderId = Literal["iproyal", "seveneleven"]


class ProxyProviderRead(StrictModel):
    id: ProviderId
    name: str
    configured: bool


class ProxyProviderConfigWrite(StrictModel):
    provider: ProviderId
    api_token: str | None = Field(default=None, max_length=500, json_schema_extra={"writeOnly": True})
    username: str | None = Field(default=None, max_length=200, json_schema_extra={"writeOnly": True})
    password: str | None = Field(default=None, max_length=500, json_schema_extra={"writeOnly": True})


class GenerateProxiesWrite(StrictModel):
    provider: ProviderId
    count: int = Field(ge=1, le=50)
    country: str = Field(default="", max_length=80)
    session_type: Literal["rotating", "sticky"]


class GenerateProxiesResultRead(StrictModel):
    created: int
    proxy_ids: list[str]


# Included before the main proxies router so "/proxies/providers" resolves here
# instead of matching "/proxies/{proxy_id}".
router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get(
    "/proxies/providers",
    response_model=list[ProxyProviderRead],
    operation_id="proxy_providers_list",
)
def list_providers_route(request: Request):
    return list_providers(request.app.state.credential_store)


@router.put(
    "/proxies/providers/{provider}",
    response_model=ProxyProviderRead,
    operation_id="proxy_providers_save",
)
def save_provider_route(provider: ProviderId, payload: ProxyProviderConfigWrite, request: Request):
    if payload.provider != provider:
        raise ManagerError(
            "proxy_provider_mismatch", "Provider in the path and body must match.", 422
        )
    return save_provider_credentials(
        request.app.state.credential_store,
        provider,
        api_token=payload.api_token,
        username=payload.username,
        password=payload.password,
    )


@router.post(
    "/proxies/providers/generate",
    response_model=GenerateProxiesResultRead,
    operation_id="proxy_providers_generate",
)
def generate_route(payload: GenerateProxiesWrite, request: Request, session: SessionDependency):
    return generate_and_store(
        session,
        request.app.state.credential_store,
        request.app.state.proxy_provider_client,
        provider=payload.provider,
        count=payload.count,
        country=payload.country,
        session_type=payload.session_type,
    )
