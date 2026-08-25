from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from contextlib import asynccontextmanager, suppress
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.api.jobs import upload_tickets_router
from app.api.admin import router as admin_router
from app.api.mobile import router as mobile_router
from app.ai.deepseek import DeepSeekClient
from app.ai.whisper import FasterWhisperTranscriber
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.engine import ResilientAlignmentEngine
from app.alignment.mms import MMSForcedAligner, SubprocessMMSRuntime
from app.core.active_jobs import ActiveJobLimiter
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.event_logging import StructuredEventLogger, event_context, exception_details
from app.core.runtime import validate_processing_runtime
from app.core.worker_config import (
    WorkerConfigReloader,
    load_worker_config,
)
from app.schemas.jobs import HealthResponse
from app.lyrics.processor import (
    DeepSeekReadingReviewer,
    LocalJapaneseLyricProcessor,
    ReviewedLyricProcessor,
)
from app.tasks.pipeline import TranscriptionPipeline
from app.tasks.runner import LocalTaskRunner
from app.tasks.cleanup import JobCleanupService, PeriodicCleanupRunner
from app.subtitle.kirakara_generator import KirakaraAssGenerator
from app.video.audio import FFmpegAudioExtractor
from app.video.rendering import FFmpegVideoRenderer
from app.vocal.mdx import MDXNetVocalRemover
from app.vocal.remover import VocalRemover


def build_vocal_remover(settings: Settings):
    if settings.vocal_removal_backend == "stft":
        return VocalRemover()
    return MDXNetVocalRemover(
        model_dir=settings.vocal_removal_model_dir,
        model_filename=settings.vocal_removal_model,
    )


def build_alignment_engine(
    settings: Settings,
    *,
    fa_kara_limiter: Any | None = None,
    event_logger: Any | None = None,
):
    fallback = LyricTimelineAligner()
    if not settings.fa_kara_enabled:
        return fallback
    return ResilientAlignmentEngine(
        primary=MMSForcedAligner(
            runtime=SubprocessMMSRuntime(
                device=settings.fa_kara_device,
                audio_speed=settings.fa_kara_audio_speed,
                silence_window_seconds=(
                    settings.fa_kara_silence_window_seconds
                ),
                silence_top_percent=(
                    settings.fa_kara_silence_top_percent
                ),
                silence_threshold_ratio=(
                    settings.fa_kara_silence_threshold_ratio
                ),
                tail_window_seconds=settings.fa_kara_tail_window_seconds,
                limiter=fa_kara_limiter,
            ),
            timeout_seconds=settings.fa_kara_timeout_seconds,
            min_confidence=settings.fa_kara_min_confidence,
        ),
        fallback=fallback,
        event_logger=event_logger,
    )


def build_pipeline(
    settings: Settings,
    database: Database,
    *,
    fa_kara_limiter: Any | None = None,
) -> TranscriptionPipeline:
    local_lyric_processor = LocalJapaneseLyricProcessor()
    if settings.deepseek_api_key is not None:
        lyric_processor = ReviewedLyricProcessor(
            base=local_lyric_processor,
            reviewer=DeepSeekReadingReviewer(
                client=DeepSeekClient(
                    api_key=settings.deepseek_api_key.get_secret_value(),
                    base_url=settings.deepseek_base_url,
                    model=settings.deepseek_model,
                    timeout_seconds=settings.deepseek_timeout_seconds,
                )
            ),
            event_logger=database.event_logger,
        )
    else:
        lyric_processor = local_lyric_processor
    return TranscriptionPipeline(
        database=database,
        extractor=FFmpegAudioExtractor(
            command=(settings.ffmpeg_path,),
            timeout_seconds=settings.ffmpeg_timeout_seconds,
        ),
        transcriber=FasterWhisperTranscriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        ),
        vocal_remover=build_vocal_remover(settings),
        lyric_processor=lyric_processor,
        aligner=build_alignment_engine(
            settings,
            fa_kara_limiter=fa_kara_limiter,
            event_logger=database.event_logger,
        ),
        subtitle_generator=KirakaraAssGenerator(),
        video_renderer=FFmpegVideoRenderer(
            command=(settings.ffmpeg_path,),
            timeout_seconds=(
                settings.video_render_timeout_seconds
            ),
            preset=settings.video_render_preset,
            crf=settings.video_render_crf,
        ),
    )


def create_app(
    settings: Settings | None = None,
    *,
    runner: Any | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app_log_level = getattr(
            logging,
            resolved_settings.log_level.upper(),
            logging.INFO,
        )
        logging.getLogger("app").setLevel(app_log_level)
        logging.getLogger("nicokara.events").setLevel(app_log_level)
        if runner is None and resolved_settings.processing_enabled:
            validate_processing_runtime(resolved_settings)
        resolved_settings.prepare_directories()
        database = Database(resolved_settings.database_path)
        database.initialize()
        event_logger = StructuredEventLogger(
            database=database,
            event_log_level=resolved_settings.event_log_level,
            debug_enabled=resolved_settings.event_log_debug,
            json_console=resolved_settings.json_console_logs,
            console_level=resolved_settings.log_level,
            progress_throttle_seconds=(
                resolved_settings.event_log_progress_throttle_seconds
            ),
        )
        database.configure_event_logger(event_logger)
        database.recover_interrupted_jobs()
        cleanup_runner = None
        if resolved_settings.cleanup_enabled:
            cleanup_runner = PeriodicCleanupRunner(
                JobCleanupService(
                    database=database,
                    storage_dir=resolved_settings.storage_dir,
                    retention_hours=resolved_settings.job_retention_hours,
                    upload_ticket_timeout_seconds=(
                        resolved_settings.upload_ticket_timeout_seconds
                    ),
                    upload_ticket_upload_timeout_seconds=(
                        resolved_settings.upload_ticket_upload_timeout_seconds
                    ),
                    max_upload_slots=resolved_settings.max_upload_slots,
                    event_log_retention_days=(
                        resolved_settings.event_log_retention_days
                    ),
                    event_log_max_rows=(
                        resolved_settings.event_log_max_rows
                    ),
                ),
                interval_seconds=(
                    resolved_settings.cleanup_interval_seconds
                ),
            )
        active_runner = runner
        worker_config_reloader = None
        if active_runner is None and resolved_settings.processing_enabled:
            worker_config = load_worker_config(
                resolved_settings.worker_config_path
            )
            fa_kara_limiter = threading.BoundedSemaphore(
                resolved_settings.fa_kara_max_concurrent_alignments
            )
            pipeline_factory = lambda: build_pipeline(
                resolved_settings,
                database,
                fa_kara_limiter=fa_kara_limiter,
            )
            pipeline = pipeline_factory()
            active_runner = LocalTaskRunner(
                pipeline,
                pipeline_factory=pipeline_factory,
                max_pending_jobs=resolved_settings.max_pending_jobs,
                worker_count=worker_config.worker_count,
                heartbeat_interval_seconds=(
                    resolved_settings.worker_heartbeat_interval_seconds
                ),
                event_logger=event_logger,
            )
            worker_config_reloader = WorkerConfigReloader(
                path=resolved_settings.worker_config_path,
                runner=active_runner,
                reload_interval_seconds=(
                    worker_config.reload_interval_seconds
                ),
            )
        app.state.settings = resolved_settings
        app.state.database = database
        app.state.event_logger = event_logger
        app.state.runner = active_runner
        app.state.worker_config_reloader = worker_config_reloader
        app.state.active_job_limiter = ActiveJobLimiter(
            database=database,
            max_active_jobs=resolved_settings.max_active_jobs_per_client,
        )
        if cleanup_runner is not None:
            await cleanup_runner.start()
        if active_runner is not None:
            await active_runner.start()
            if worker_config_reloader is not None:
                await worker_config_reloader.start()
            pending_job_ids = database.list_job_ids(status="UPLOADED")
            recovery_task = None
            enqueue_wait = getattr(active_runner, "enqueue_wait", None)
            if enqueue_wait is not None:
                async def recover_pending_jobs() -> None:
                    for pending_job_id in pending_job_ids:
                        event_logger.emit(
                            event="job.recovered_to_queue",
                            level="INFO",
                            category="system",
                            message="服务启动后恢复等待处理的任务。",
                            job_id=pending_job_id,
                            component="startup_recovery",
                            details={
                                "pending_job_count": len(pending_job_ids)
                            },
                        )
                        await enqueue_wait(pending_job_id)

                recovery_task = asyncio.create_task(recover_pending_jobs())
            else:
                for pending_job_id in pending_job_ids:
                    if not getattr(active_runner, "can_accept", True):
                        break
                    event_logger.emit(
                        event="job.recovered_to_queue",
                        level="INFO",
                        category="system",
                        message="服务启动后恢复等待处理的任务。",
                        job_id=pending_job_id,
                        component="startup_recovery",
                        details={
                            "pending_job_count": len(pending_job_ids)
                        },
                    )
                    await active_runner.enqueue(pending_job_id)
        try:
            yield
        finally:
            if worker_config_reloader is not None:
                await worker_config_reloader.stop()
            if active_runner is not None and recovery_task is not None:
                recovery_task.cancel()
                with suppress(asyncio.CancelledError):
                    await recovery_task
            if active_runner is not None:
                await active_runner.stop()
            if cleanup_runner is not None:
                await cleanup_runner.stop()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.3.0-alpha.3",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        path = request.url.path
        method = request.method.upper()
        job_match = re.search(
            r"/jobs/([0-9a-fA-F-]{36})(?:/|$)",
            path,
        )
        ticket_match = re.search(
            r"/(?:upload-tickets|audio-uploads)/([^/]+)(?:/|$)",
            path,
        )
        reference_id = (
            job_match.group(1)
            if job_match
            else ticket_match.group(1)
            if ticket_match
            else None
        )
        reference_type = (
            "job" if job_match else "upload_ticket" if ticket_match else None
        )
        chunk_upload_request = (
            method == "POST"
            and re.fullmatch(
                rf"{re.escape(resolved_settings.api_prefix)}"
                r"/(?:upload-tickets|browser/audio-uploads)"
                r"/[^/]+/chunks/part/\d+",
                path,
            )
            is not None
        )
        suppress_event = (
            chunk_upload_request
            or path in {"/health", "/api/v1/health"}
            or (
                method == "GET"
                and re.fullmatch(r"/api/v1/jobs/[0-9a-fA-F-]{36}", path)
                is not None
            )
            or (
                method == "GET"
                and re.fullmatch(
                    r"/api/v1/upload-tickets/[0-9a-fA-F-]{36}",
                    path,
                )
                is not None
            )
            or path in {"/api/v1/admin/overview", "/api/v1/admin/logs"}
            or (
                method == "GET"
                and path.startswith("/api/v1/admin/jobs/")
                and path.endswith("/timeline")
            )
        )
        event_logger = getattr(app.state, "event_logger", None)
        started = time.perf_counter()
        with event_context(request_id=request_id, component="fastapi"):
            if event_logger is not None and not suppress_event:
                event_logger.emit(
                    event="request.started",
                    level="INFO",
                    category="request",
                    message="收到 HTTP 请求",
                    reference_type=reference_type,
                    reference_id=reference_id,
                    details={"method": method, "route": path},
                )
            try:
                response = await call_next(request)
            except Exception as exc:
                if event_logger is not None and not suppress_event:
                    event_logger.emit(
                        event="request.failed",
                        level="ERROR",
                        category="request",
                        message="HTTP 请求处理异常",
                        reference_type=reference_type,
                        reference_id=reference_id,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        details={
                            "method": method,
                            "route": path,
                            **exception_details(exc),
                        },
                    )
                raise
            if event_logger is not None and not suppress_event:
                route = request.scope.get("route")
                route_path = getattr(route, "path", path)
                event_logger.emit(
                    event="request.completed",
                    level="WARNING" if response.status_code >= 400 else "INFO",
                    category="request",
                    message="HTTP 请求处理完成",
                    reference_type=reference_type,
                    reference_id=reference_id,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    details={
                        "method": method,
                        "route": route_path,
                        "status_code": response.status_code,
                    },
                )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response
    app.include_router(jobs_router, prefix=resolved_settings.api_prefix)
    app.include_router(
        upload_tickets_router,
        prefix=resolved_settings.api_prefix,
    )
    app.include_router(admin_router, prefix=resolved_settings.api_prefix)
    app.include_router(mobile_router, prefix=resolved_settings.api_prefix)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
