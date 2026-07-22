from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .schemas import (
    AutomationRecordingRead,
    AutomationRunRead,
    AutomationTemplateRead,
    CredentialImport,
    CredentialPoolSummary,
    ProfileFactoryJobRead,
    RecordingCreate,
    StartFactoryPayload,
    StartRunPayload,
    TemplateWrite,
)
from . import service
from .service import template_to_dict


router = APIRouter(prefix="/automations", tags=["automation"])
SessionDependency = Annotated[Session, Depends(get_session)]
_ACCEPTED = status.HTTP_202_ACCEPTED
_NO_CONTENT = status.HTTP_204_NO_CONTENT


# --- templates --------------------------------------------------------------
@router.get("/templates", response_model=list[AutomationTemplateRead], operation_id="automation_templates_list")
def list_templates(session: SessionDependency):
    return service.list_templates(session)


@router.get("/templates/{template_id}", response_model=AutomationTemplateRead, operation_id="automation_templates_get")
def get_template(template_id: str, session: SessionDependency):
    return template_to_dict(service.get_template(session, template_id))


@router.put("/templates/{template_id}", response_model=AutomationTemplateRead, operation_id="automation_templates_save")
def save_template(template_id: str, payload: TemplateWrite, session: SessionDependency):
    steps = [step.model_dump(exclude_none=True) for step in payload.steps]
    return service.save_template(
        session, template_id, name=payload.name, description=payload.description, steps=steps
    )


@router.delete("/templates/{template_id}", status_code=_NO_CONTENT, operation_id="automation_templates_delete")
def delete_template(template_id: str, session: SessionDependency) -> Response:
    service.delete_template(session, template_id)
    return Response(status_code=_NO_CONTENT)


# --- recordings -------------------------------------------------------------
@router.post("/recordings", response_model=AutomationRecordingRead, status_code=_ACCEPTED, operation_id="automation_recordings_create")
def create_recording(payload: RecordingCreate, request: Request, session: SessionDependency):
    return service.start_recording(
        session,
        request.app.state.automation_controller,
        name=payload.name,
        profile_id=payload.profile_id,
        description=payload.description,
    )


@router.get("/recordings/{recording_id}", response_model=AutomationRecordingRead, operation_id="automation_recordings_get")
def get_recording(recording_id: str, request: Request, session: SessionDependency):
    return service.get_recording(session, request.app.state.automation_controller, recording_id)


@router.post("/recordings/{recording_id}/stop", response_model=AutomationTemplateRead, operation_id="automation_recordings_stop")
def stop_recording(recording_id: str, request: Request, session: SessionDependency):
    return service.stop_recording(session, request.app.state.automation_controller, recording_id)


@router.post("/recordings/{recording_id}/cancel", status_code=_NO_CONTENT, operation_id="automation_recordings_cancel")
def cancel_recording(recording_id: str, request: Request, session: SessionDependency) -> Response:
    service.cancel_recording(session, request.app.state.automation_controller, recording_id)
    return Response(status_code=_NO_CONTENT)


# --- runs -------------------------------------------------------------------
@router.post("/templates/{template_id}/runs", response_model=AutomationRunRead, status_code=_ACCEPTED, operation_id="automation_runs_start")
def start_run(template_id: str, payload: StartRunPayload, request: Request, session: SessionDependency):
    template = service.get_template(session, template_id)
    return request.app.state.automation_runs.start(
        session, template, payload.assignments, payload.max_parallel
    )


@router.get("/runs/{run_id}", response_model=AutomationRunRead, operation_id="automation_runs_get")
def get_run(run_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_runs.get_run(session, run_id)


@router.post("/runs/{run_id}/cancel", response_model=AutomationRunRead, operation_id="automation_runs_cancel")
def cancel_run(run_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_runs.cancel(session, run_id)


@router.post("/runs/{run_id}/profiles/{profile_id}/continue", response_model=AutomationRunRead, operation_id="automation_runs_continue")
def continue_profile(run_id: str, profile_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_runs.continue_profile(session, run_id, profile_id)


@router.post("/runs/{run_id}/profiles/{profile_id}/retry", response_model=AutomationRunRead, operation_id="automation_runs_retry")
def retry_profile(run_id: str, profile_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_runs.retry_profile(session, run_id, profile_id)


@router.post("/runs/{run_id}/profiles/{profile_id}/mark-completed", response_model=AutomationRunRead, operation_id="automation_runs_mark_completed")
def mark_completed(run_id: str, profile_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_runs.mark_completed(session, run_id, profile_id)


# --- credentials ------------------------------------------------------------
@router.get("/credentials", response_model=CredentialPoolSummary, operation_id="automation_credentials_summary")
def credential_summary(session: SessionDependency):
    return service.credential_summary(session)


@router.post("/credentials/import", response_model=CredentialPoolSummary, operation_id="automation_credentials_import")
def import_credentials(payload: CredentialImport, request: Request, session: SessionDependency):
    return service.import_credentials(session, request.app.state.credential_store, payload.text)


# --- factory ----------------------------------------------------------------
@router.get("/factory/jobs", response_model=list[ProfileFactoryJobRead], operation_id="automation_factory_list")
def list_factory_jobs(request: Request, session: SessionDependency):
    return request.app.state.automation_factory.list_jobs(session)


@router.post("/factory/jobs", response_model=ProfileFactoryJobRead, status_code=_ACCEPTED, operation_id="automation_factory_start")
def start_factory_job(payload: StartFactoryPayload, request: Request, session: SessionDependency):
    return request.app.state.automation_factory.start(
        session,
        quantity=payload.quantity,
        name_prefix=payload.name_prefix,
        automation_template_id=payload.automation_template_id,
        start_automation=payload.start_automation,
    )


@router.get("/factory/jobs/{job_id}", response_model=ProfileFactoryJobRead, operation_id="automation_factory_get")
def get_factory_job(job_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_factory.get_job(session, job_id)


@router.post("/factory/jobs/{job_id}/cancel", response_model=ProfileFactoryJobRead, operation_id="automation_factory_cancel")
def cancel_factory_job(job_id: str, request: Request, session: SessionDependency):
    return request.app.state.automation_factory.cancel(session, job_id)
