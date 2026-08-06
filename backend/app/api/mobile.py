from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.api.jobs import (
    client_key_from_request,
    enqueue_created_job,
    job_response,
    normalized_client_submission_id,
    safe_display_name,
    services,
)
from app.core.active_jobs import ActiveJobLimitError
from app.alignment.review import (
    TimelineReviewError,
    apply_timeline_review,
    lyric_timeline_from_dict,
)
from app.schemas.jobs import JobResponse
from app.services.uploads import save_audio, save_lyrics, save_mp4
from app.subtitle.kirakara_generator import KirakaraAssConfig, KirakaraAssGenerator


router = APIRouter(tags=["browser processing"])
SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
MAX_LOCAL_MEDIA_BYTES = 300 * 1024 * 1024


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
            lyrics_path=lyrics_path,
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
        or job["status"] not in {"ALIGNED", "SUBTITLE_GENERATED"}
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
