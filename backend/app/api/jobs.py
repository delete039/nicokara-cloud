from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.core.active_jobs import ActiveJobLimitError
from app.core.config import Settings
from app.core.database import Database
from app.core.rate_limit import resolve_client_key
from app.schemas.jobs import JobResponse, UploadTicketCreate, UploadTicketResponse
from app.services.uploads import save_lyrics, save_mp4


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


def services(request: Request) -> tuple[Settings, Database]:
    return request.app.state.settings, request.app.state.database


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
    database.expire_stale_upload_tickets(
        waiting_cutoff=(
            now - timedelta(seconds=settings.upload_ticket_timeout_seconds)
        ).isoformat(),
        uploading_cutoff=(
            now
            - timedelta(seconds=settings.upload_ticket_upload_timeout_seconds)
        ).isoformat(),
    )
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
    except Exception:
        logger.exception(
            "Job %s was stored but could not be added to the runner queue",
            job_id,
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
    )
    refresh_upload_queue(settings, database)
    refreshed = database.get_upload_ticket(ticket["id"]) or ticket
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
    refresh_upload_queue(settings, database)
    refreshed = database.get_upload_ticket(ticket_id) or ticket
    return upload_ticket_response(database, refreshed)


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


@router.get("/{job_id}/lyrics", response_class=FileResponse)
def get_processed_lyrics(request: Request, job_id: str) -> FileResponse:
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
    return FileResponse(
        lyrics_path,
        media_type="application/json",
        filename="lyrics_processed.json",
    )


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
