from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.jobs import refresh_upload_queue
from app.core.monitoring import collect_system_resources
from app.schemas.admin import (
    AdminActionResponse,
    AdminOverviewResponse,
    AdminQueueHealthResponse,
)
from app.services.chunked_uploads import remove_chunked_upload


router = APIRouter(prefix="/admin", tags=["admin monitoring"])
logger = logging.getLogger(__name__)


def require_admin(request: Request) -> None:
    configured = request.app.state.settings.admin_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin monitoring is not configured.",
        )
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    expected = configured.get_secret_value()
    if scheme.lower() != "bearer" or not supplied or not compare_digest(
        supplied,
        expected,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _runner_snapshot(request: Request) -> dict:
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        return {
            "healthy": False,
            "worker_count": 0,
            "alive_workers": 0,
            "queued_in_memory": 0,
            "last_heartbeat_at": None,
            "active_jobs": [],
        }
    snapshot = getattr(runner, "snapshot", None)
    if callable(snapshot):
        return snapshot()
    return {
        "healthy": True,
        "worker_count": None,
        "alive_workers": None,
        "queued_in_memory": None,
        "last_heartbeat_at": None,
        "active_jobs": [],
    }


def _audit(
    request: Request,
    *,
    action: str,
    target_type: str,
    target_id: str,
    outcome: str,
    details: str | None = None,
) -> None:
    request.app.state.database.record_admin_audit(
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        details=details,
    )
    logger.info(
        json.dumps(
            {
                "event": "admin_action",
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "outcome": outcome,
            },
            ensure_ascii=True,
        )
    )


@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    dependencies=[Depends(require_admin)],
)
def overview(request: Request) -> AdminOverviewResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    refresh_upload_queue(settings, database)
    generated_at = datetime.now(UTC)
    upload_tickets = database.list_active_upload_tickets()
    for ticket in upload_tickets:
        position, size = database.upload_ticket_metrics(ticket["id"])
        ticket["queue_position"] = position
        ticket["queue_size"] = size
    jobs = database.list_monitored_jobs()
    for job in jobs:
        updated_at = datetime.fromisoformat(job["updated_at"])
        job["stage_age_seconds"] = max(
            0,
            (generated_at - updated_at).total_seconds(),
        )
    return AdminOverviewResponse(
        generated_at=generated_at.isoformat(),
        upload_counts=database.count_upload_tickets_by_status(),
        job_counts=database.count_jobs_by_status(),
        upload_tickets=upload_tickets,
        jobs=jobs,
        runner=_runner_snapshot(request),
        resources=collect_system_resources(settings.storage_dir),
        audit_events=database.list_admin_audit_events(),
    )


@router.get(
    "/queue-health",
    response_model=AdminQueueHealthResponse,
    dependencies=[Depends(require_admin)],
)
def queue_health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    refresh_upload_queue(settings, database)
    runner = _runner_snapshot(request)
    payload = AdminQueueHealthResponse(
        status="ok" if runner["healthy"] else "degraded",
        runner_healthy=bool(runner["healthy"]),
        upload_waiting=database.count_upload_tickets_by_status().get(
            "WAITING",
            0,
        ),
        jobs_waiting=database.count_jobs_by_status().get("UPLOADED", 0),
    )
    return JSONResponse(
        status_code=200 if runner["healthy"] else 503,
        content=payload.model_dump(),
    )


@router.post(
    "/upload-tickets/{ticket_id}/cancel",
    response_model=AdminActionResponse,
    dependencies=[Depends(require_admin)],
)
def cancel_upload_ticket(
    request: Request,
    ticket_id: str,
) -> AdminActionResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    ticket = database.get_upload_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Upload ticket not found.")
    if not database.cancel_upload_ticket(ticket_id):
        raise HTTPException(status_code=409, detail="Upload ticket is not active.")
    remove_chunked_upload(settings.storage_dir, ticket_id)
    refresh_upload_queue(settings, database)
    _audit(
        request,
        action="upload_ticket.cancel",
        target_type="upload_ticket",
        target_id=ticket_id,
        outcome="succeeded",
    )
    return AdminActionResponse(id=ticket_id, status="CANCELED")


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=AdminActionResponse,
    dependencies=[Depends(require_admin)],
)
async def cancel_job(request: Request, job_id: str) -> AdminActionResponse:
    database = request.app.state.database
    if database.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not database.cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job is not active.")
    runner = getattr(request.app.state, "runner", None)
    cancel = getattr(runner, "cancel", None)
    if callable(cancel):
        await cancel(job_id)
    _audit(
        request,
        action="job.cancel",
        target_type="job",
        target_id=job_id,
        outcome="succeeded",
    )
    return AdminActionResponse(id=job_id, status="CANCELED")


@router.post(
    "/jobs/{job_id}/requeue",
    response_model=AdminActionResponse,
    dependencies=[Depends(require_admin)],
)
async def requeue_job(request: Request, job_id: str) -> AdminActionResponse:
    database = request.app.state.database
    if database.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = database.requeue_job(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="Job cannot be requeued.")
    runner = getattr(request.app.state, "runner", None)
    enqueue = getattr(runner, "enqueue", None)
    if callable(enqueue):
        try:
            await enqueue(job_id)
        except Exception as exc:
            database.update_job_state(
                job_id,
                status="FAILED",
                stage="ADMIN_REQUEUE_FAILED",
                progress=0,
                error_code="ADMIN_REQUEUE_FAILED",
                error_message="The job could not be added to the worker queue.",
            )
            _audit(
                request,
                action="job.requeue",
                target_type="job",
                target_id=job_id,
                outcome="failed",
                details=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="The worker queue rejected the job.",
            ) from exc
    _audit(
        request,
        action="job.requeue",
        target_type="job",
        target_id=job_id,
        outcome="succeeded",
    )
    return AdminActionResponse(id=job_id, status="UPLOADED")
