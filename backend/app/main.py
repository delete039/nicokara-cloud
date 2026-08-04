from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.ai.deepseek import DeepSeekClient
from app.ai.whisper import FasterWhisperTranscriber
from app.alignment.aligner import LyricTimelineAligner
from app.core.active_jobs import ActiveJobLimiter
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.schemas.jobs import HealthResponse
from app.lyrics.processor import (
    DeepSeekLyricProcessor,
    LocalJapaneseLyricProcessor,
    ResilientLyricProcessor,
)
from app.tasks.pipeline import TranscriptionPipeline
from app.tasks.runner import LocalTaskRunner
from app.tasks.cleanup import JobCleanupService, PeriodicCleanupRunner
from app.subtitle.ass_generator import AssGenerator
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


def create_app(
    settings: Settings | None = None,
    *,
    runner: Any | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.prepare_directories()
        database = Database(resolved_settings.database_path)
        database.initialize()
        database.recover_interrupted_jobs()
        cleanup_runner = None
        if resolved_settings.cleanup_enabled:
            cleanup_runner = PeriodicCleanupRunner(
                JobCleanupService(
                    database=database,
                    storage_dir=resolved_settings.storage_dir,
                    retention_hours=resolved_settings.job_retention_hours,
                ),
                interval_seconds=(
                    resolved_settings.cleanup_interval_seconds
                ),
            )
        active_runner = runner
        if active_runner is None and resolved_settings.processing_enabled:
            local_lyric_processor = LocalJapaneseLyricProcessor()
            if resolved_settings.deepseek_api_key is not None:
                lyric_processor = ResilientLyricProcessor(
                    primary=DeepSeekLyricProcessor(
                        client=DeepSeekClient(
                            api_key=resolved_settings.deepseek_api_key.get_secret_value(),
                            base_url=resolved_settings.deepseek_base_url,
                            model=resolved_settings.deepseek_model,
                            timeout_seconds=resolved_settings.deepseek_timeout_seconds,
                        )
                    ),
                    fallback=local_lyric_processor,
                )
            else:
                lyric_processor = local_lyric_processor
            active_runner = LocalTaskRunner(
                TranscriptionPipeline(
                    database=database,
                    extractor=FFmpegAudioExtractor(
                        command=(resolved_settings.ffmpeg_path,),
                        timeout_seconds=resolved_settings.ffmpeg_timeout_seconds,
                    ),
                    transcriber=FasterWhisperTranscriber(
                        model_name=resolved_settings.whisper_model,
                        device=resolved_settings.whisper_device,
                        compute_type=resolved_settings.whisper_compute_type,
                    ),
                    vocal_remover=build_vocal_remover(
                        resolved_settings
                    ),
                    lyric_processor=lyric_processor,
                    aligner=LyricTimelineAligner(),
                    subtitle_generator=AssGenerator(),
                    video_renderer=FFmpegVideoRenderer(
                        command=(resolved_settings.ffmpeg_path,),
                        timeout_seconds=(
                            resolved_settings.video_render_timeout_seconds
                        ),
                        preset=resolved_settings.video_render_preset,
                        crf=resolved_settings.video_render_crf,
                    ),
                ),
                max_pending_jobs=resolved_settings.max_pending_jobs,
            )
        app.state.settings = resolved_settings
        app.state.database = database
        app.state.runner = active_runner
        app.state.active_job_limiter = ActiveJobLimiter(
            database=database,
            max_active_jobs=resolved_settings.max_active_jobs_per_client,
        )
        if cleanup_runner is not None:
            await cleanup_runner.start()
        if active_runner is not None:
            await active_runner.start()
            pending_job_ids = database.list_job_ids(status="UPLOADED")
            recovery_task = None
            enqueue_wait = getattr(active_runner, "enqueue_wait", None)
            if enqueue_wait is not None:
                async def recover_pending_jobs() -> None:
                    for pending_job_id in pending_job_ids:
                        await enqueue_wait(pending_job_id)

                recovery_task = asyncio.create_task(recover_pending_jobs())
            else:
                for pending_job_id in pending_job_ids:
                    if not getattr(active_runner, "can_accept", True):
                        break
                    await active_runner.enqueue(pending_job_id)
        try:
            yield
        finally:
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
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response
    app.include_router(jobs_router, prefix=resolved_settings.api_prefix)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
