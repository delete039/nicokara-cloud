from __future__ import annotations

from dataclasses import replace
import json
import logging
import re
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response

from app.alignment.review import (
    TimelineReviewError,
    apply_timeline_review,
    lyric_timeline_from_dict,
)
from app.alignment.models import LyricTimeline
from app.core.active_jobs import ActiveJobLimitError
from app.core.config import Settings
from app.core.database import Database
from app.core.event_logging import exception_details
from app.core.rate_limit import resolve_client_key
from app.schemas.jobs import (
    JobResponse,
    ReadingReviewRequest,
    UploadChunkResponse,
    UploadChunkSessionCreate,
    UploadChunkSessionResponse,
    UploadTicketCreate,
    UploadTicketResponse,
)
from app.services.chunked_uploads import (
    acquire_completion_lock,
    assemble_chunked_mp4,
    missing_chunk_indices,
    read_chunked_upload_metadata,
    received_chunk_count,
    remove_chunked_upload,
    save_upload_chunk,
    start_chunked_upload,
)
from app.services.uploads import save_lyrics, save_mp4
from app.lyrics.models import LyricDocument, lyric_document_from_dict
from app.lyrics.processor import normalize_unconverted_foreign_readings
from app.subtitle.kirakara_generator import KirakaraAssConfig, KirakaraAssGenerator


router = APIRouter(prefix="/jobs", tags=["jobs"])
upload_tickets_router = APIRouter(
    prefix="/upload-tickets",
    tags=["upload queue"],
)
logger = logging.getLogger(__name__)


def safe_display_name(filename: str | None) -> str:
    candidate = Path(filename or "input.mp4").name
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate).strip()
    return candidate[:255] or "input.mp4"


def normalized_client_submission_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        UUID(candidate)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_submission_id must be a UUID.",
        ) from exc
    return candidate


def services(request: Request) -> tuple[Settings, Database]:
    return request.app.state.settings, request.app.state.database


def request_event_logger(request: Request):
    return getattr(request.app.state, "event_logger", None)


def client_key_from_request(request: Request, settings: Settings) -> str:
    peer_host = request.client.host if request.client else "unknown"
    return resolve_client_key(
        peer_host=peer_host,
        forwarded_for=(
            request.headers.get("x-forwarded-for")
            or request.headers.get("x-real-ip")
        ),
        trusted_proxies=settings.trusted_proxies,
    )


def job_response(database: Database, job: dict) -> JobResponse:
    queue_position, queue_size = database.queue_metrics(job["id"])
    return JobResponse.model_validate(
        {
            **job,
            "queue_position": queue_position,
            "queue_size": queue_size,
        }
    )


def refresh_upload_queue(settings: Settings, database: Database) -> None:
    now = datetime.now(UTC)
    expired_ticket_ids = database.expire_stale_upload_tickets(
        waiting_cutoff=(
            now - timedelta(seconds=settings.upload_ticket_timeout_seconds)
        ).isoformat(),
        uploading_cutoff=(
            now
            - timedelta(seconds=settings.upload_ticket_upload_timeout_seconds)
        ).isoformat(),
    )
    for ticket_id in expired_ticket_ids:
        remove_chunked_upload(settings.storage_dir, ticket_id)
    database.activate_upload_tickets(
        max_active_uploads=settings.max_upload_slots,
    )


def upload_ticket_response(
    database: Database,
    ticket: dict,
) -> UploadTicketResponse:
    queue_position, queue_size = database.upload_ticket_metrics(ticket["id"])
    return UploadTicketResponse.model_validate(
        {
            **ticket,
            "queue_position": queue_position,
            "queue_size": queue_size,
        }
    )


async def enqueue_created_job(request: Request, job_id: str) -> None:
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        return
    enqueue = getattr(runner, "enqueue", None)
    if enqueue is None:
        logger.warning("Configured runner cannot enqueue job %s", job_id)
        return
    try:
        await enqueue(job_id)
    except Exception as exc:
        safe_error = exception_details(exc, include_traceback=False)
        logger.error(
            "Job %s was stored but could not be added to the runner queue (%s: %s)",
            job_id,
            safe_error["exception_type"],
            safe_error["error_summary"],
        )


@upload_tickets_router.post(
    "",
    response_model=UploadTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload_ticket(
    request: Request,
    payload: UploadTicketCreate,
) -> UploadTicketResponse:
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    client_key = client_key_from_request(request, settings)
    original_name = safe_display_name(payload.video_name)
    client_submission_id = normalized_client_submission_id(
        payload.client_submission_id
    )
    if client_submission_id is not None:
        existing_job = database.get_job_by_client_submission_id(
            client_submission_id
        )
        if existing_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Client submission already created a job.",
            )
    if Path(original_name).suffix.lower() != ".mp4":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="第一版仅支持 .mp4 视频",
        )
    if payload.video_size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="视频文件为空",
        )
    if payload.video_size_bytes > settings.max_video_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="视频文件超过大小限制",
        )
    active_count = (
        database.count_active_jobs_for_client(client_key)
        + database.count_active_upload_tickets_for_client(client_key)
    )
    if active_count >= settings.max_active_jobs_per_client:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many active jobs for this client. Try again later."
            ),
            headers={"Retry-After": "60"},
        )

    ticket = database.create_upload_ticket(
        ticket_id=str(uuid4()),
        client_key=client_key,
        video_name=original_name,
        video_size_bytes=payload.video_size_bytes,
        client_submission_id=client_submission_id,
    )
    refresh_upload_queue(settings, database)
    refreshed = database.get_upload_ticket(ticket["id"]) or ticket
    queue_position, queue_size = database.upload_ticket_metrics(ticket["id"])
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.ticket_created",
            level="INFO",
            category="upload",
            message="上传票据创建完成",
            reference_type="upload_ticket",
            reference_id=ticket["id"],
            component="upload_queue",
            details={
                "file_size_bytes": payload.video_size_bytes,
                "queue_position": queue_position,
                "queue_size": queue_size,
                "status": refreshed["status"],
            },
        )
    return upload_ticket_response(database, refreshed)


@upload_tickets_router.get(
    "/{ticket_id}",
    response_model=UploadTicketResponse,
)
def get_upload_ticket(
    request: Request,
    ticket_id: str,
) -> UploadTicketResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.get_upload_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )
    if ticket["status"] in {"WAITING", "READY"}:
        database.touch_upload_ticket(ticket_id)
        refresh_upload_queue(settings, database)
        ticket = database.get_upload_ticket(ticket_id) or ticket
    return upload_ticket_response(database, ticket)


@upload_tickets_router.post(
    "/{ticket_id}/cancel",
    response_model=UploadTicketResponse,
)
def cancel_upload_ticket(
    request: Request,
    ticket_id: str,
) -> UploadTicketResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.get_upload_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )
    database.cancel_upload_ticket(ticket_id)
    remove_chunked_upload(settings.storage_dir, ticket_id)
    refresh_upload_queue(settings, database)
    refreshed = database.get_upload_ticket(ticket_id) or ticket
    return upload_ticket_response(database, refreshed)


@upload_tickets_router.post(
    "/{ticket_id}/chunks/start",
    response_model=UploadChunkSessionResponse,
)
def start_upload_chunks(
    request: Request,
    ticket_id: str,
    payload: UploadChunkSessionCreate,
) -> UploadChunkSessionResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.begin_upload_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )

    if not ticket.get("_upload_started"):
        if ticket["status"] == "UPLOADING":
            metadata = read_chunked_upload_metadata(
                settings.storage_dir,
                ticket_id,
            )
            return UploadChunkSessionResponse(
                ticket_id=ticket_id,
                status=ticket["status"],
                chunk_size_bytes=int(metadata["chunk_size_bytes"]),
                total_chunks=int(metadata["total_chunks"]),
                received_chunks=received_chunk_count(
                    settings.storage_dir,
                    ticket_id,
                ),
            )
        status_code = (
            status.HTTP_409_CONFLICT
            if ticket["status"] == "WAITING"
            else status.HTTP_410_GONE
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"Upload ticket is {ticket['status'].lower()}.",
        )

    original_name = safe_display_name(payload.video_name)
    if original_name != ticket["video_name"]:
        original_name = ticket["video_name"]
    if Path(original_name).suffix.lower() != ".mp4":
        database.cancel_upload_ticket(ticket_id)
        remove_chunked_upload(settings.storage_dir, ticket_id)
        refresh_upload_queue(settings, database)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="绗竴鐗堜粎鏀寔 .mp4 瑙嗛",
        )
    if payload.video_size_bytes != ticket["video_size_bytes"]:
        database.cancel_upload_ticket(ticket_id)
        remove_chunked_upload(settings.storage_dir, ticket_id)
        refresh_upload_queue(settings, database)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video size does not match the upload ticket.",
        )

    try:
        metadata = start_chunked_upload(
            settings.storage_dir,
            ticket_id,
            video_name=original_name,
            video_size_bytes=payload.video_size_bytes,
            chunk_size_bytes=payload.chunk_size_bytes,
            total_chunks=payload.total_chunks,
        )
    except Exception:
        database.cancel_upload_ticket(ticket_id)
        remove_chunked_upload(settings.storage_dir, ticket_id)
        refresh_upload_queue(settings, database)
        raise
    database.touch_uploading_ticket(ticket_id)
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.session_started",
            level="INFO",
            category="upload",
            message="视频分片上传会话已建立",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_upload",
            details={
                "file_size_bytes": payload.video_size_bytes,
                "chunk_size_bytes": payload.chunk_size_bytes,
                "total_chunks": payload.total_chunks,
            },
        )
    return UploadChunkSessionResponse(
        ticket_id=ticket_id,
        status="UPLOADING",
        chunk_size_bytes=int(metadata["chunk_size_bytes"]),
        total_chunks=int(metadata["total_chunks"]),
        received_chunks=0,
    )


@upload_tickets_router.post(
    "/{ticket_id}/chunks/part/{chunk_index}",
    response_model=UploadChunkResponse,
)
async def upload_video_chunk(
    request: Request,
    ticket_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...),
) -> UploadChunkResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        await chunk.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.get_upload_ticket(ticket_id)
    if ticket is None:
        await chunk.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )
    if ticket["status"] != "UPLOADING":
        await chunk.close()
        status_code = (
            status.HTTP_409_CONFLICT
            if ticket["status"] == "WAITING"
            else status.HTTP_410_GONE
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"Upload ticket is {ticket['status'].lower()}.",
        )

    result = await save_upload_chunk(
        settings.storage_dir,
        ticket_id,
        chunk_index,
        chunk,
    )
    database.touch_uploading_ticket(ticket_id)
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.chunk_received",
            level="DEBUG",
            category="upload",
            message="视频分片接收完成",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_upload",
            details={
                "chunk_index": chunk_index,
                "received_chunks": result["received_chunks"],
                "total_chunks": result["total_chunks"],
            },
        )
    return UploadChunkResponse(
        ticket_id=ticket_id,
        chunk_index=chunk_index,
        received_chunks=result["received_chunks"],
        total_chunks=result["total_chunks"],
    )


@upload_tickets_router.post(
    "/{ticket_id}/chunks/complete",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_upload_chunks(
    request: Request,
    ticket_id: str,
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    vocal_mode: str = Form(default="on"),
) -> JobResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.get_upload_ticket(ticket_id)
    if ticket is None:
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )
    if ticket["status"] == "COMPLETED" and ticket.get("job_id"):
        if lyrics_file:
            await lyrics_file.close()
        existing_job = database.get_job(ticket["job_id"])
        if existing_job is not None:
            return job_response(database, existing_job)
    if ticket["status"] != "UPLOADING":
        if lyrics_file:
            await lyrics_file.close()
        status_code = (
            status.HTTP_409_CONFLICT
            if ticket["status"] == "WAITING"
            else status.HTTP_410_GONE
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"Upload ticket is {ticket['status'].lower()}.",
        )

    try:
        missing = missing_chunk_indices(settings.storage_dir, ticket_id)
    except HTTPException:
        if lyrics_file:
            await lyrics_file.close()
        raise
    if missing:
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload chunks are incomplete.",
        )

    try:
        acquire_completion_lock(settings.storage_dir, ticket_id)
    except HTTPException:
        if lyrics_file:
            await lyrics_file.close()
        raise
    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    video_path = job_dir / "input.mp4"
    lyrics_path = job_dir / "lyrics.txt"
    original_name = ticket["video_name"]
    created = False
    merge_started = time.perf_counter()
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.merge_started",
            level="INFO",
            category="upload",
            message="开始合并并校验视频分片",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_upload",
            details={"expected_size_bytes": ticket["video_size_bytes"]},
        )
    try:
        saved = assemble_chunked_mp4(
            settings.storage_dir,
            ticket_id,
            video_path,
            max_bytes=settings.max_video_bytes,
        )
        if event_logger is not None:
            event_logger.emit(
                event="upload.merge_completed",
                level="INFO",
                category="upload",
                message="视频分片合并及大小、哈希校验完成",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                component="chunked_upload",
                duration_ms=(time.perf_counter() - merge_started) * 1000,
                details={
                    "expected_size_bytes": ticket["video_size_bytes"],
                    "actual_size_bytes": saved.size_bytes,
                    "sha256": saved.sha256,
                    "size_verified": (
                        saved.size_bytes == ticket["video_size_bytes"]
                    ),
                },
            )
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        job = database.create_job(
            job_id=job_id,
            original_video_name=original_name,
            video_size_bytes=saved.size_bytes,
            video_sha256=saved.sha256,
            video_path=saved.path,
            client_key=ticket["client_key"],
            lyrics_source=lyrics_source,
            lyrics_path=lyrics_path if lyrics_source else None,
            vocal_mode=vocal_mode,
            client_submission_id=ticket.get("client_submission_id"),
        )
        created = True
        if not database.complete_upload_ticket(ticket_id, job_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Upload ticket is no longer active.",
            )
        remove_chunked_upload(settings.storage_dir, ticket_id)
        refresh_upload_queue(settings, database)
        await enqueue_created_job(request, job_id)
        if event_logger is not None:
            event_logger.emit(
                event="upload.job_created",
                level="INFO",
                category="upload",
                message="上传完成并创建处理任务",
                reference_type="job",
                reference_id=job_id,
                component="chunked_upload",
                details={
                    "upload_ticket_id": ticket_id,
                    "file_size_bytes": saved.size_bytes,
                    "lyrics_provided": lyrics_source is not None,
                    "vocal_mode": vocal_mode,
                },
            )
    except Exception as exc:
        if event_logger is not None:
            event_logger.emit(
                event="upload.failed",
                level="ERROR",
                category="upload",
                message="视频分片合并或任务创建失败",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                component="chunked_upload",
                duration_ms=(time.perf_counter() - merge_started) * 1000,
                details=exception_details(exc),
            )
        if created:
            database.delete_job(job_id)
        database.cancel_upload_ticket(ticket_id)
        remove_chunked_upload(settings.storage_dir, ticket_id)
        refresh_upload_queue(settings, database)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    current_job = database.get_job(job_id) or job
    return job_response(database, current_job)


@upload_tickets_router.post(
    "/{ticket_id}/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_from_upload_ticket(
    request: Request,
    ticket_id: str,
    video: UploadFile = File(...),
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    vocal_mode: str = Form(default="on"),
) -> JobResponse:
    try:
        UUID(ticket_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        ) from exc
    settings, database = services(request)
    refresh_upload_queue(settings, database)
    ticket = database.begin_upload_ticket(ticket_id)
    if ticket is None:
        await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传排队号不存在",
        )
    if not ticket.get("_upload_started"):
        await video.close()
        if lyrics_file:
            await lyrics_file.close()
        if ticket["status"] == "COMPLETED" and ticket.get("job_id"):
            existing_job = database.get_job(ticket["job_id"])
            if existing_job is not None:
                return job_response(database, existing_job)
        status_code = (
            status.HTTP_409_CONFLICT
            if ticket["status"] == "WAITING"
            else status.HTTP_410_GONE
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"Upload ticket is {ticket['status'].lower()}.",
        )

    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    video_path = job_dir / "input.mp4"
    lyrics_path = job_dir / "lyrics.txt"
    original_name = safe_display_name(video.filename)
    if original_name != ticket["video_name"]:
        original_name = ticket["video_name"]
    if Path(original_name).suffix.lower() != ".mp4":
        await video.close()
        if lyrics_file:
            await lyrics_file.close()
        database.cancel_upload_ticket(ticket_id)
        refresh_upload_queue(settings, database)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="第一版仅支持 .mp4 视频",
        )

    created = False
    try:
        saved = await save_mp4(
            video,
            video_path,
            max_bytes=settings.max_video_bytes,
        )
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        job = database.create_job(
            job_id=job_id,
            original_video_name=original_name,
            video_size_bytes=saved.size_bytes,
            video_sha256=saved.sha256,
            video_path=saved.path,
            client_key=ticket["client_key"],
            lyrics_source=lyrics_source,
            lyrics_path=lyrics_path if lyrics_source else None,
            vocal_mode=vocal_mode,
            client_submission_id=ticket.get("client_submission_id"),
        )
        created = True
        if not database.complete_upload_ticket(ticket_id, job_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Upload ticket is no longer active.",
            )
        refresh_upload_queue(settings, database)
        await enqueue_created_job(request, job_id)
    except Exception:
        if created:
            database.delete_job(job_id)
        database.cancel_upload_ticket(ticket_id)
        refresh_upload_queue(settings, database)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    current_job = database.get_job(job_id) or job
    return job_response(database, current_job)


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    video: UploadFile = File(...),
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    vocal_mode: str = Form(default="on"),
) -> JobResponse:
    settings, database = services(request)
    client_key = client_key_from_request(request, settings)
    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    video_path = job_dir / "input.mp4"
    lyrics_path = job_dir / "lyrics.txt"

    original_name = safe_display_name(video.filename)
    if Path(original_name).suffix.lower() != ".mp4":
        await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="第一版仅支持 .mp4 视频",
        )

    active_job_reservation = None
    try:
        active_job_reservation = request.app.state.active_job_limiter.reserve(
            client_key
        )
    except ActiveJobLimitError as exc:
        await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many active jobs for this client. Try again later."
            ),
            headers={"Retry-After": "60"},
        ) from exc

    created = False
    try:
        saved = await save_mp4(
            video,
            video_path,
            max_bytes=settings.max_video_bytes,
        )
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        job = database.create_job(
            job_id=job_id,
            original_video_name=original_name,
            video_size_bytes=saved.size_bytes,
            video_sha256=saved.sha256,
            video_path=saved.path,
            client_key=client_key,
            lyrics_source=lyrics_source,
            lyrics_path=lyrics_path if lyrics_source else None,
            vocal_mode=vocal_mode,
        )
        created = True
        active_job_reservation.commit()
        active_job_reservation = None
        await enqueue_created_job(request, job_id)
    except Exception:
        if created:
            database.delete_job(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        if active_job_reservation is not None:
            active_job_reservation.release()
    current_job = database.get_job(job_id) or job
    return job_response(database, current_job)


@router.get(
    "/by-submission/{client_submission_id}",
    response_model=JobResponse,
)
def get_job_by_client_submission_id(
    request: Request,
    client_submission_id: str,
) -> JobResponse:
    normalized = normalized_client_submission_id(client_submission_id)
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    _, database = services(request)
    job = database.get_job_by_client_submission_id(normalized)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    return job_response(database, job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    _, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return job_response(database, job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(request: Request, job_id: str) -> JobResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc

    _, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    if job["status"] == "CANCELED":
        return job_response(database, job)
    if not database.cancel_job(job_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前任务已经结束，无法取消。",
        )

    runner = getattr(request.app.state, "runner", None)
    cancel = getattr(runner, "cancel", None) if runner is not None else None
    if cancel is not None:
        await cancel(job_id)

    canceled_job = database.get_job(job_id)
    if canceled_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return job_response(database, canceled_job)


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_failed_job(request: Request, job_id: str) -> JobResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc

    _, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    reservation = None
    try:
        reservation = request.app.state.active_job_limiter.reserve(
            job["client_key"]
        )
    except ActiveJobLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前用户已有任务正在处理，请等待任务完成后再重试。",
            headers={"Retry-After": "60"},
        ) from exc

    try:
        retried_job = database.retry_failed_job(job_id)
        if retried_job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="只有处理失败的任务可以重新加入队列。",
            )
        reservation.commit()
        reservation = None
    finally:
        if reservation is not None:
            reservation.release()

    runner = getattr(request.app.state, "runner", None)
    enqueue = getattr(runner, "enqueue", None) if runner is not None else None
    if enqueue is not None:
        try:
            await enqueue(job_id)
        except Exception as exc:
            safe_error = exception_details(exc, include_traceback=False)
            logger.error(
                "Retried job %s could not be enqueued (%s: %s)",
                job_id,
                safe_error["exception_type"],
                safe_error["error_summary"],
            )
            database.update_job_state(
                job_id,
                status="FAILED",
                stage="RETRY_QUEUE_FAILED",
                progress=0,
                error_code="RETRY_QUEUE_FAILED",
                error_message="服务器暂时无法将任务重新加入处理队列。",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="任务重新入队失败，请稍后重试。",
            ) from exc

    current_job = database.get_job(job_id) or retried_job
    return job_response(database, current_job)


@router.get("/{job_id}/transcript", response_class=FileResponse)
def get_transcript(request: Request, job_id: str) -> FileResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    transcript_path_value = job.get("transcript_path")
    if not transcript_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="转录尚未完成",
        )
    transcript_path = validated_job_file(
        settings, job_id, transcript_path_value
    )
    if not transcript_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="转录文件不存在",
        )
    return FileResponse(
        transcript_path,
        media_type="application/json",
        filename="transcript.json",
    )


@router.get("/{job_id}/lyrics")
def get_processed_lyrics(request: Request, job_id: str) -> Response:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    lyrics_path_value = job.get("lyrics_processed_path")
    if not lyrics_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理尚未完成",
        )
    lyrics_path = validated_job_file(
        settings, job_id, lyrics_path_value
    )
    if not lyrics_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="歌词处理文件不存在",
        )
    try:
        document = lyric_document_from_dict(
            json.loads(lyrics_path.read_text(encoding="utf-8"))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理文件无法读取",
        ) from exc
    normalized = normalize_unconverted_foreign_readings(document)
    if normalized is document:
        return FileResponse(
            lyrics_path,
            media_type="application/json",
            filename="lyrics_processed.json",
        )
    return Response(
        content=json.dumps(normalized.to_dict(), ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="lyrics_processed.json"'
        },
    )


@router.post("/{job_id}/readings", response_model=JobResponse)
async def confirm_readings(
    request: Request,
    job_id: str,
    payload: ReadingReviewRequest,
) -> JobResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc

    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    if (
        job["status"] != "LYRICS_PROCESSED"
        or job["stage"] != "READING_REVIEW_REQUIRED"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前任务不在注音确认阶段",
        )
    lyrics_path_value = job.get("lyrics_processed_path")
    if not lyrics_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理文件尚未生成",
        )
    lyrics_path = validated_job_file(
        settings,
        job_id,
        lyrics_path_value,
    )
    if not lyrics_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="歌词处理文件不存在",
        )

    try:
        document = lyric_document_from_dict(
            json.loads(lyrics_path.read_text(encoding="utf-8"))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理文件无法读取",
        ) from exc

    if len(payload.lines) != len(document.lines):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="歌词行数与处理结果不一致",
        )

    reviewed_lines = []
    for source_line, reviewed_line in zip(
        document.lines,
        payload.lines,
        strict=True,
    ):
        if reviewed_line.surface != source_line.surface:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="歌词表面文字不允许在注音确认阶段修改",
            )
        if len(reviewed_line.tokens) != len(source_line.tokens):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="歌词词元数量与处理结果不一致",
            )

        reviewed_tokens = []
        for source_token, reviewed_token in zip(
            source_line.tokens,
            reviewed_line.tokens,
            strict=True,
        ):
            if reviewed_token.surface != source_token.surface:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="歌词表面文字不允许在注音确认阶段修改",
                )
            if source_token.surface.isspace():
                reviewed_tokens.append(source_token)
                continue
            reading = reviewed_token.reading.strip() or source_token.reading
            reviewed_tokens.append(
                replace(
                    source_token,
                    reading=reading,
                    alignment_pronunciation=(
                        source_token.alignment_pronunciation
                        if reading == source_token.reading
                        else None
                    ),
                )
            )
        reviewed_lines.append(
            replace(
                source_line,
                reading="".join(token.reading for token in reviewed_tokens),
                tokens=reviewed_tokens,
            )
        )

    reviewed_document = replace(document, lines=reviewed_lines)
    if not database.claim_reading_review(job_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="注音已由其他请求确认或任务状态已变更",
        )
    temporary_path = lyrics_path.with_name(
        f".{lyrics_path.name}.{uuid4().hex}.reviewed.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(
                reviewed_document.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(lyrics_path)
        if not database.queue_alignment(job_id):
            raise RuntimeError("Reading review state could not be queued")
    except Exception:
        temporary_path.unlink(missing_ok=True)
        database.update_job_state(
            job_id,
            status="LYRICS_PROCESSED",
            stage="READING_REVIEW_REQUIRED",
            progress=80,
            lyrics_processed_path=lyrics_path,
        )
        raise
    await enqueue_created_job(request, job_id)
    queued_job = database.get_job(job_id)
    if queued_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return job_response(database, queued_job)


@router.get("/{job_id}/timeline", response_class=FileResponse)
def get_timeline(request: Request, job_id: str) -> FileResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    timeline_path_value = job.get("timeline_path")
    if not timeline_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词时间轴尚未完成",
        )
    timeline_path = validated_job_file(
        settings, job_id, timeline_path_value
    )
    if not timeline_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="歌词时间轴文件不存在",
        )
    return FileResponse(
        timeline_path,
        media_type="application/json",
        filename="timeline.json",
    )


@router.get("/{job_id}/subtitle", response_class=FileResponse)
def get_subtitle(request: Request, job_id: str) -> FileResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    ass_path_value = job.get("ass_path")
    if not ass_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ASS 字幕尚未生成",
        )
    ass_path = validated_job_file(
        settings, job_id, ass_path_value
    )
    if not ass_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="ASS 字幕文件不存在",
        )
    return FileResponse(
        ass_path,
        media_type="text/x-ssa; charset=utf-8",
        filename="lyrics.ass",
    )


def _reviewed_lyrics_document(
    document: LyricDocument,
    reviewed_timeline: LyricTimeline,
) -> LyricDocument:
    if len(document.lines) != len(reviewed_timeline.lines):
        raise TimelineReviewError("processed lyric lines do not match timeline")

    reviewed_lines = []
    for document_line, timeline_line in zip(
        document.lines,
        reviewed_timeline.lines,
        strict=True,
    ):
        if (
            document_line.surface != timeline_line.surface
            or len(document_line.tokens) != len(timeline_line.tokens)
        ):
            raise TimelineReviewError("processed lyrics do not match timeline")
        reviewed_tokens = []
        for document_token, timeline_token in zip(
            document_line.tokens,
            timeline_line.tokens,
            strict=True,
        ):
            if document_token.surface != timeline_token.surface:
                raise TimelineReviewError("processed lyrics do not match timeline")
            reviewed_tokens.append(
                replace(
                    document_token,
                    reading=timeline_token.reading,
                    alignment_pronunciation=(
                        document_token.alignment_pronunciation
                        if timeline_token.reading == document_token.reading
                        else None
                    ),
                )
            )
        reviewed_lines.append(
            replace(
                document_line,
                reading="".join(token.reading for token in reviewed_tokens),
                tokens=reviewed_tokens,
            )
        )

    warnings = list(document.warnings)
    if "browser_reviewed" not in warnings:
        warnings.append("browser_reviewed")
    return replace(document, lines=reviewed_lines, warnings=warnings)


@router.post("/{job_id}/exports/{artifact}", response_class=Response)
def export_reviewed_artifact(
    request: Request,
    job_id: str,
    artifact: str,
    review: dict[str, Any],
) -> Response:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    if artifact not in {"lyrics", "timeline", "subtitle"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="不支持的导出格式",
        )

    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    timeline_path_value = job.get("timeline_path")
    if not timeline_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词时间轴尚未完成",
        )
    timeline_path = validated_job_file(settings, job_id, timeline_path_value)

    try:
        source_timeline = lyric_timeline_from_dict(
            json.loads(timeline_path.read_text(encoding="utf-8"))
        )
        reviewed_timeline = apply_timeline_review(source_timeline, review)
    except (json.JSONDecodeError, TimelineReviewError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"时间轴校正数据无效：{exc}",
        ) from exc

    if artifact == "timeline":
        content = json.dumps(
            reviewed_timeline.to_dict(),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    'attachment; filename="timeline.reviewed.json"'
                )
            },
        )

    if artifact == "subtitle":
        content = KirakaraAssGenerator(
            config=KirakaraAssConfig.from_browser_style(review.get("style"))
        ).generate(reviewed_timeline)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/x-ssa",
            headers={
                "Content-Disposition": (
                    'attachment; filename="lyrics.reviewed.ass"'
                )
            },
        )

    lyrics_path_value = job.get("lyrics_processed_path")
    if not lyrics_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理尚未完成",
        )
    lyrics_path = validated_job_file(settings, job_id, lyrics_path_value)
    try:
        document = lyric_document_from_dict(
            json.loads(lyrics_path.read_text(encoding="utf-8"))
        )
        reviewed_document = _reviewed_lyrics_document(
            document,
            reviewed_timeline,
        )
    except TimelineReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"注音校正数据无效：{exc}",
        ) from exc
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词处理文件无法读取",
        ) from exc
    content = json.dumps(
        reviewed_document.to_dict(),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                'attachment; filename="lyrics_processed.reviewed.json"'
            )
        },
    )


@router.get("/{job_id}/instrumental", response_class=FileResponse)
def get_instrumental_audio(request: Request, job_id: str) -> FileResponse:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    if job.get("vocal_mode", "on") != "off":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ON VOCAL 任务不生成云端伴奏",
        )
    instrumental_path = settings.storage_dir / job_id / "audio_instrumental.wav"
    if not instrumental_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="伴奏音频尚未生成",
        )
    instrumental_path = validated_job_file(
        settings,
        job_id,
        str(instrumental_path),
    )
    return FileResponse(
        instrumental_path,
        media_type="audio/wav",
        filename="instrumental.wav",
    )


@router.get("/{job_id}/result", response_class=FileResponse)
def get_result_video(request: Request, job_id: str) -> FileResponse:
    output_path = result_video_path(request, job_id)
    return FileResponse(
        output_path,
        media_type="video/mp4",
    )


@router.get("/{job_id}/download", response_class=FileResponse)
def download_result_video(request: Request, job_id: str) -> FileResponse:
    output_path = result_video_path(request, job_id)
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename="final_karaoke.mp4",
    )


def result_video_path(request: Request, job_id: str) -> Path:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    output_path_value = job.get("output_path")
    if not output_path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="最终视频尚未生成",
        )
    output_path = validated_job_file(
        settings, job_id, output_path_value
    )
    if not output_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="最终视频文件不存在",
        )
    return output_path


def validated_job_file(
    settings: Settings,
    job_id: str,
    path_value: str,
) -> Path:
    job_dir = (settings.storage_dir / job_id).resolve()
    candidate = Path(path_value).resolve()
    if candidate.parent != job_dir or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Requested task file is no longer available.",
        )
    return candidate
