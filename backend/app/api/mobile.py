from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.jobs import (
    client_key_from_request,
    enqueue_created_job,
    job_response,
    normalized_client_submission_id,
    request_event_logger,
    safe_display_name,
    services,
)
from app.core.active_jobs import ActiveJobLimitError
from app.core.event_logging import exception_details
from app.alignment.review import (
    TimelineReviewError,
    apply_timeline_review,
    lyric_timeline_from_dict,
)
from app.schemas.jobs import (
    AudioUploadSessionCreate,
    AudioUploadSessionResponse,
    JobResponse,
    UploadChunkResponse,
)
from app.services.chunked_uploads import (
    acquire_completion_lock,
    assemble_chunked_audio,
    missing_chunk_indices,
    read_chunked_upload_metadata,
    received_chunk_indices,
    remove_chunked_upload,
    save_upload_chunk,
    start_chunked_upload,
    touch_chunked_upload,
)
from app.services.uploads import save_audio, save_lyrics, save_mp4
from app.services.reviewed_artifacts import (
    ensure_lyrics_source_from_reviewed_artifacts,
    save_reviewed_artifacts,
)
from app.subtitle.kirakara_generator import KirakaraAssConfig, KirakaraAssGenerator


router = APIRouter(tags=["browser processing"])
SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
MAX_LOCAL_MEDIA_BYTES = 300 * 1024 * 1024
AUDIO_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024


def audio_upload_response(
    settings,
    ticket_id: str,
    metadata: dict,
) -> AudioUploadSessionResponse:
    received = received_chunk_indices(settings.storage_dir, ticket_id)
    missing = missing_chunk_indices(settings.storage_dir, ticket_id)
    return AudioUploadSessionResponse(
        ticket_id=ticket_id,
        status="UPLOADING",
        chunk_size_bytes=int(metadata["chunk_size_bytes"]),
        total_chunks=int(metadata["total_chunks"]),
        received_chunks=len(received),
        received_chunk_indices=received,
        missing_chunk_indices=missing,
    )


@router.post(
    "/browser/audio-uploads",
    response_model=AudioUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_or_resume_audio_upload(
    request: Request,
    payload: AudioUploadSessionCreate,
    response: Response,
) -> AudioUploadSessionResponse:
    settings, database = services(request)
    submission_id = normalized_client_submission_id(payload.client_submission_id)
    if submission_id is None:
        raise HTTPException(status_code=400, detail="client_submission_id is required.")
    if database.get_job_by_client_submission_id(submission_id) is not None:
        raise HTTPException(status_code=409, detail="Client submission already created a job.")

    original_video_name = safe_display_name(payload.original_video_name)
    if Path(original_video_name).suffix.lower() != ".mp4":
        raise HTTPException(status_code=422, detail="original_video_name must identify an MP4 video.")
    if not 0 < payload.original_video_size_bytes <= MAX_LOCAL_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="本地素材必须小于或等于 300 MB")

    audio_name = safe_display_name(payload.audio_name)
    audio_suffix = Path(audio_name).suffix.lower()
    if audio_suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 WAV、MP3、M4A、AAC、FLAC 或 OGG 音频")
    if not 0 < payload.audio_size_bytes <= settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="音频文件超过大小限制")
    if payload.chunk_size_bytes != AUDIO_UPLOAD_CHUNK_BYTES:
        raise HTTPException(status_code=400, detail="音频分片大小必须为 8 MiB")

    ticket_id = submission_id
    try:
        metadata = read_chunked_upload_metadata(settings.storage_dir, ticket_id)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        metadata = start_chunked_upload(
            settings.storage_dir,
            ticket_id,
            video_name=audio_name,
            video_size_bytes=payload.audio_size_bytes,
            chunk_size_bytes=payload.chunk_size_bytes,
            total_chunks=payload.total_chunks,
            extra_metadata={
                "upload_kind": "audio",
                "original_video_name": original_video_name,
                "original_video_size_bytes": payload.original_video_size_bytes,
                "client_key": client_key_from_request(request, settings),
                "client_submission_id": submission_id,
            },
        )
    else:
        response.status_code = status.HTTP_200_OK
        expected = {
            "upload_kind": "audio",
            "video_name": audio_name,
            "video_size_bytes": payload.audio_size_bytes,
            "chunk_size_bytes": payload.chunk_size_bytes,
            "total_chunks": payload.total_chunks,
            "original_video_name": original_video_name,
            "original_video_size_bytes": payload.original_video_size_bytes,
            "client_submission_id": submission_id,
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise HTTPException(status_code=409, detail="Audio upload session metadata does not match.")
        touch_chunked_upload(settings.storage_dir, ticket_id)
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.audio_session_ready",
            level="INFO",
            category="upload",
            message="音频分片上传会话已就绪",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_audio_upload",
            details={
                "resumed": response.status_code == status.HTTP_200_OK,
                "audio_size_bytes": payload.audio_size_bytes,
                "chunk_size_bytes": payload.chunk_size_bytes,
                "total_chunks": payload.total_chunks,
                "original_video_size_bytes": (
                    payload.original_video_size_bytes
                ),
            },
        )
    return audio_upload_response(settings, ticket_id, metadata)


@router.post(
    "/browser/audio-uploads/{ticket_id}/chunks/part/{chunk_index}",
    response_model=UploadChunkResponse,
)
async def upload_audio_chunk(
    request: Request,
    ticket_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...),
) -> UploadChunkResponse:
    try:
        normalized_client_submission_id(ticket_id)
    except HTTPException:
        await chunk.close()
        raise
    settings, _ = services(request)
    try:
        metadata = read_chunked_upload_metadata(settings.storage_dir, ticket_id)
    except HTTPException:
        await chunk.close()
        raise
    if metadata.get("upload_kind") != "audio":
        await chunk.close()
        raise HTTPException(status_code=404, detail="Audio upload session does not exist.")
    result = await save_upload_chunk(
        settings.storage_dir,
        ticket_id,
        chunk_index,
        chunk,
    )
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.audio_chunk_received",
            level="DEBUG",
            category="upload",
            message="音频分片接收完成",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_audio_upload",
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


@router.post(
    "/browser/audio-uploads/{ticket_id}/complete",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_audio_upload(
    request: Request,
    ticket_id: str,
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    project_files: list[UploadFile] = File(default=[]),
    vocal_mode: str = Form(default="on"),
) -> JobResponse:
    try:
        normalized_client_submission_id(ticket_id)
    except HTTPException:
        if lyrics_file is not None:
            await lyrics_file.close()
        raise
    settings, database = services(request)
    existing = database.get_job_by_client_submission_id(ticket_id)
    if existing is not None:
        if lyrics_file is not None:
            await lyrics_file.close()
        remove_chunked_upload(settings.storage_dir, ticket_id)
        return job_response(database, existing)
    try:
        metadata = read_chunked_upload_metadata(settings.storage_dir, ticket_id)
    except HTTPException:
        if lyrics_file is not None:
            await lyrics_file.close()
        raise
    if metadata.get("upload_kind") != "audio":
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(status_code=404, detail="Audio upload session does not exist.")
    missing = missing_chunk_indices(settings.storage_dir, ticket_id)
    if missing:
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(status_code=409, detail="Audio upload chunks are incomplete.")
    try:
        completion_lock = acquire_completion_lock(settings.storage_dir, ticket_id)
    except Exception:
        if lyrics_file is not None:
            await lyrics_file.close()
        raise

    reservation = None
    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    audio_suffix = Path(str(metadata["video_name"])).suffix.lower()
    audio_path = job_dir / f"input_audio{audio_suffix}"
    lyrics_path = job_dir / "lyrics.txt"
    created = False
    merge_started = time.perf_counter()
    event_logger = request_event_logger(request)
    if event_logger is not None:
        event_logger.emit(
            event="upload.audio_merge_started",
            level="INFO",
            category="upload",
            message="开始合并并校验音频分片",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            component="chunked_audio_upload",
            details={
                "expected_size_bytes": metadata["video_size_bytes"],
                "total_chunks": metadata["total_chunks"],
            },
        )
    try:
        reservation = request.app.state.active_job_limiter.reserve(
            str(metadata["client_key"])
        )
        saved = assemble_chunked_audio(
            settings.storage_dir,
            ticket_id,
            audio_path,
            max_bytes=settings.max_audio_bytes,
        )
        if event_logger is not None:
            event_logger.emit(
                event="upload.audio_merge_completed",
                level="INFO",
                category="upload",
                message="音频分片合并及大小、哈希校验完成",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                component="chunked_audio_upload",
                duration_ms=(time.perf_counter() - merge_started) * 1000,
                details={
                    "expected_size_bytes": metadata["video_size_bytes"],
                    "actual_size_bytes": saved.size_bytes,
                    "sha256": saved.sha256,
                    "size_verified": (
                        saved.size_bytes == metadata["video_size_bytes"]
                    ),
                },
            )
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        reviewed = await save_reviewed_artifacts(
            project_files,
            job_dir,
            max_bytes=max(settings.max_lyrics_bytes, 4 * 1024 * 1024),
        )
        lyrics_source, effective_lyrics_path = (
            ensure_lyrics_source_from_reviewed_artifacts(
                reviewed,
                lyrics_path,
                lyrics_source,
            )
        )
        if lyrics_source is None:
            raise HTTPException(status_code=422, detail="音频任务必须提供歌词")
        job = database.create_job(
            job_id=job_id,
            original_video_name=str(metadata["original_video_name"]),
            video_size_bytes=int(metadata["original_video_size_bytes"]),
            video_sha256=saved.sha256,
            video_path=saved.path,
            client_key=str(metadata["client_key"]),
            lyrics_source=lyrics_source,
            lyrics_path=effective_lyrics_path,
            vocal_mode=vocal_mode,
            client_submission_id=ticket_id,
            input_mode="AUDIO_ONLY",
            source_upload_size_bytes=saved.size_bytes,
            source_upload_sha256=saved.sha256,
        )
        created = True
        reservation.commit()
        reservation = None
        await enqueue_created_job(request, job_id)
        remove_chunked_upload(settings.storage_dir, ticket_id)
        if event_logger is not None:
            event_logger.emit(
                event="upload.audio_job_created",
                level="INFO",
                category="upload",
                message="音频上传完成并创建云端分析任务",
                reference_type="job",
                reference_id=job_id,
                component="chunked_audio_upload",
                details={
                    "upload_ticket_id": ticket_id,
                    "audio_size_bytes": saved.size_bytes,
                    "lyrics_provided": True,
                    "input_mode": "AUDIO_ONLY",
                },
            )
    except ActiveJobLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many active jobs for this client. Try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    except Exception as exc:
        if event_logger is not None:
            event_logger.emit(
                event="upload.audio_failed",
                level="ERROR",
                category="upload",
                message="音频分片合并或任务创建失败",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                component="chunked_audio_upload",
                duration_ms=(time.perf_counter() - merge_started) * 1000,
                details=exception_details(exc),
            )
        if created:
            database.delete_job(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        if reservation is not None:
            reservation.release()
        if lyrics_file is not None:
            await lyrics_file.close()
        completion_lock.unlink(missing_ok=True)
    return job_response(database, database.get_job(job_id) or job)


@router.post(
    "/browser/audio-jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/mobile/audio-jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_audio_only_job(
    request: Request,
    audio: UploadFile = File(...),
    original_video_name: str = Form(...),
    original_video_size_bytes: int = Form(...),
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    project_files: list[UploadFile] = File(default=[]),
    vocal_mode: str = Form(default="on"),
    client_submission_id: str | None = Form(default=None),
) -> JobResponse:
    settings, database = services(request)
    normalized_submission_id = normalized_client_submission_id(
        client_submission_id
    )
    if normalized_submission_id is not None:
        existing = database.get_job_by_client_submission_id(
            normalized_submission_id
        )
        if existing is not None:
            await audio.close()
            if lyrics_file is not None:
                await lyrics_file.close()
            return job_response(database, existing)

    display_video_name = safe_display_name(original_video_name)
    if Path(display_video_name).suffix.lower() != ".mp4":
        await audio.close()
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="original_video_name must identify an MP4 video.",
        )
    if not 0 < original_video_size_bytes <= MAX_LOCAL_MEDIA_BYTES:
        await audio.close()
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="本地素材必须小于或等于 300 MB",
        )

    audio_name = safe_display_name(audio.filename or "input_audio.wav")
    audio_suffix = Path(audio_name).suffix.lower()
    if audio_suffix not in SUPPORTED_AUDIO_SUFFIXES:
        await audio.close()
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 WAV、MP3、M4A、AAC、FLAC 或 OGG 音频",
        )

    client_key = client_key_from_request(request, settings)
    reservation = None
    try:
        reservation = request.app.state.active_job_limiter.reserve(client_key)
    except ActiveJobLimitError as exc:
        await audio.close()
        if lyrics_file is not None:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many active jobs for this client. Try again later.",
            headers={"Retry-After": "60"},
        ) from exc

    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    audio_path = job_dir / f"input_audio{audio_suffix}"
    lyrics_path = job_dir / "lyrics.txt"
    created = False
    try:
        saved = await save_audio(
            audio,
            audio_path,
            max_bytes=settings.max_audio_bytes,
        )
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        reviewed = await save_reviewed_artifacts(
            project_files,
            job_dir,
            max_bytes=max(settings.max_lyrics_bytes, 4 * 1024 * 1024),
        )
        lyrics_source, effective_lyrics_path = (
            ensure_lyrics_source_from_reviewed_artifacts(
                reviewed,
                lyrics_path,
                lyrics_source,
            )
        )
        if lyrics_source is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="音频任务必须提供歌词",
            )
        job = database.create_job(
            job_id=job_id,
            original_video_name=display_video_name,
            video_size_bytes=original_video_size_bytes,
            video_sha256=saved.sha256,
            video_path=saved.path,
            client_key=client_key,
            lyrics_source=lyrics_source,
            lyrics_path=effective_lyrics_path,
            vocal_mode=vocal_mode,
            client_submission_id=normalized_submission_id,
            input_mode="AUDIO_ONLY",
            source_upload_size_bytes=saved.size_bytes,
            source_upload_sha256=saved.sha256,
        )
        created = True
        reservation.commit()
        reservation = None
        await enqueue_created_job(request, job_id)
    except Exception:
        if created:
            database.delete_job(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        if reservation is not None:
            reservation.release()

    return job_response(database, database.get_job(job_id) or job)


@router.post(
    "/browser/jobs/{job_id}/cloud-render",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_audio_job_for_cloud_render(
    job_id: str,
    request: Request,
    video: UploadFile = File(...),
    timeline_review: str = Form(...),
) -> JobResponse:
    settings, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        await video.close()
        raise HTTPException(status_code=404, detail="任务不存在或已经过期")
    if (
        job.get("input_mode") != "AUDIO_ONLY"
        or job["status"] not in {"ALIGNED", "SUBTITLE_GENERATED", "COMPLETED"}
    ):
        await video.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前任务不能进入云端仅渲染队列",
        )
    if safe_display_name(video.filename) != job["original_video_name"]:
        await video.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="选择的视频文件名与音频任务的原视频不一致",
        )

    timeline_path_value = job.get("timeline_path")
    if not timeline_path_value or not Path(timeline_path_value).is_file():
        await video.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务时间轴尚未生成，不能开始云端渲染",
        )
    try:
        review_data = json.loads(timeline_review)
        source_data = json.loads(
            Path(timeline_path_value).read_text(encoding="utf-8")
        )
        reviewed_timeline = apply_timeline_review(
            lyric_timeline_from_dict(source_data),
            review_data,
        )
    except (json.JSONDecodeError, TimelineReviewError) as exc:
        await video.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"时间轴校正数据无效：{exc}",
        ) from exc

    client_key = client_key_from_request(request, settings)
    reservation = None
    temp_dir = settings.storage_dir / job_id / f".cloud-render-{uuid4()}"
    try:
        reservation = request.app.state.active_job_limiter.reserve(client_key)
        saved = await save_mp4(
            video,
            temp_dir / "input.mp4",
            max_bytes=settings.max_video_bytes,
        )
        if saved.size_bytes != job["video_size_bytes"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="选择的视频大小与音频任务记录的原视频不一致",
            )

        reviewed_path = temp_dir / "timeline.json"
        reviewed_path.write_text(
            json.dumps(
                reviewed_timeline.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        ass_path = temp_dir / "kirakara.ass"
        ass_path.write_text(
            KirakaraAssGenerator(
                config=KirakaraAssConfig.from_browser_style(
                    review_data.get("style")
                )
            ).generate(reviewed_timeline),
            encoding="utf-8-sig",
        )

        job_dir = settings.storage_dir / job_id
        final_video_path = job_dir / "input.mp4"
        final_timeline_path = job_dir / "timeline.json"
        final_ass_path = job_dir / "kirakara.ass"
        saved.path.replace(final_video_path)
        reviewed_path.replace(final_timeline_path)
        ass_path.replace(final_ass_path)
        queued = database.queue_cloud_render(
            job_id,
            video_path=final_video_path,
            video_size_bytes=saved.size_bytes,
            video_sha256=saved.sha256,
            timeline_path=final_timeline_path,
            ass_path=final_ass_path,
        )
        if not queued:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="任务状态已变化，请刷新页面后重试",
            )
        reservation.commit()
        reservation = None
        await enqueue_created_job(request, job_id)
    except ActiveJobLimitError as exc:
        await video.close()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前客户端已有任务正在处理，请稍后再试",
            headers={"Retry-After": "60"},
        ) from exc
    finally:
        if reservation is not None:
            reservation.release()
        shutil.rmtree(temp_dir, ignore_errors=True)

    updated = database.get_job(job_id)
    if updated is None:
        raise RuntimeError("Queued cloud render job could not be read back")
    return job_response(database, updated)
