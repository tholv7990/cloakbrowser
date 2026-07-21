from __future__ import annotations

from fastapi import APIRouter, Request

from .schemas import SettingsPatch, SettingsRead
from . import service


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead, operation_id="settings_get")
def get_settings(request: Request) -> SettingsRead:
    preferences = request.app.state.settings_store.load()
    return service.build_settings_read(request.app.state.settings, preferences)


@router.patch("", response_model=SettingsRead, operation_id="settings_patch")
def patch_settings(request: Request, payload: SettingsPatch) -> SettingsRead:
    preferences = request.app.state.settings_store.patch(payload)
    return service.build_settings_read(request.app.state.settings, preferences)


@router.post(
    "/browser/check-update",
    response_model=SettingsRead,
    operation_id="settings_check_browser_update",
)
def check_browser_update(request: Request) -> SettingsRead:
    service.update_entitled_binary()
    preferences = request.app.state.settings_store.load()
    return service.build_settings_read(request.app.state.settings, preferences)
