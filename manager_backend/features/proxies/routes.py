from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .parser import parse_proxy
from .schemas import (
    ParsedProxyRead,
    ProxyParseRequest,
    ProxyQuickTestRead,
    ProxyRead,
    ProxyWrite,
)
from .service import (
    create_proxy,
    delete_proxy,
    get_proxy,
    list_proxies,
    proxy_to_dict,
    update_proxy,
    cache_quick_test,
    resolve_proxy_url,
)
from .testing import ProxyTestFailure
from ...errors import ManagerError


router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/proxies", response_model=list[ProxyRead])
def proxies(session: SessionDependency):
    return list_proxies(session)


@router.post("/proxies", response_model=ProxyRead, status_code=status.HTTP_201_CREATED)
def create(payload: ProxyWrite, request: Request, session: SessionDependency):
    proxy = create_proxy(session, request.app.state.credential_store, payload)
    return proxy_to_dict(session, proxy)


@router.post("/proxies/parse", response_model=ParsedProxyRead)
def parse(payload: ProxyParseRequest):
    parsed = parse_proxy(payload.raw)
    return {
        "scheme": parsed.scheme,
        "host": parsed.host,
        "port": parsed.port,
        "username": parsed.username,
        "has_password": parsed.password is not None,
    }


@router.get("/proxies/{proxy_id}", response_model=ProxyRead)
def get(proxy_id: str, session: SessionDependency):
    return proxy_to_dict(session, get_proxy(session, proxy_id))


@router.patch("/proxies/{proxy_id}", response_model=ProxyRead)
def patch(proxy_id: str, payload: ProxyWrite, request: Request, session: SessionDependency):
    proxy = update_proxy(session, request.app.state.credential_store, proxy_id, payload)
    return proxy_to_dict(session, proxy)


@router.delete("/proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(proxy_id: str, request: Request, session: SessionDependency) -> Response:
    delete_proxy(session, request.app.state.credential_store, proxy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/proxies/{proxy_id}/quick-test", response_model=ProxyQuickTestRead)
def quick_test(proxy_id: str, request: Request, session: SessionDependency):
    proxy = get_proxy(session, proxy_id)
    proxy_url = resolve_proxy_url(session, request.app.state.credential_store, proxy_id)
    if proxy_url is None:
        raise ManagerError(
            "proxy_test_not_applicable", "Direct connections do not require a proxy test.", 422
        )
    try:
        result = request.app.state.proxy_quick_tester.run(proxy_url, timeout_seconds=20)
    except ProxyTestFailure as error:
        return {
            "ok": False,
            "connectivity": False,
            "exit_ip": None,
            "exit_ip_matches": None,
            "latency_ms": None,
            "country": None,
            "city": None,
            "timezone": None,
            "asn": None,
            "organization": None,
            "checked_at": datetime.now(timezone.utc),
            "error": error.category,
        }
    cache_quick_test(session, proxy, result)
    return {
        "ok": True,
        "connectivity": True,
        "exit_ip": result.exit_ip,
        "exit_ip_matches": result.exit_ip_matches,
        "latency_ms": result.latency_ms,
        "country": result.country,
        "city": result.city,
        "timezone": result.timezone,
        "asn": result.asn,
        "organization": result.organization,
        "checked_at": result.checked_at,
        "error": None,
    }
