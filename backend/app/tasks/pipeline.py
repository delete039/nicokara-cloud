from __future__ import annotations

import json
import logging
import time
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.database import Database, JobCanceledError
from app.core.event_logging import (
    StructuredEventLogger,
    current_event_context,
    event_context,
    exception_details,
)
from app.ai.whisper import transcript_document_from_dict
from app.lyrics.lrc import parse_lrc, retime_timeline_from_lrc
from app.lyrics.models import lyric_document_from_dict
from app.video.audio import FFmpegUnavailableError


logger = logging.getLogger(__name__)

PUBLIC_ERROR_MESSAGES = {
    "REMOVING_VOCALS": (
        "服务器未完成人声与伴奏分离。请使用任务 ID 查询 UVR 处理日志。"
    ),
    "EXTRACTING_AUDIO": (
        "服务器无法读取素材中的音轨。请使用任务 ID 查询 FFmpeg 日志。"
    ),
    "TRANSCRIBING": (
        "服务器未能生成歌声时间信息。请使用任务 ID 查询语音分析日志。"
    ),
    "PROCESSING_LYRICS": (
        "服务器无法解析歌词或注音格式。请检查歌词后使用任务 ID 查询日志。"
    ),
    "ALIGNING": (
        "FA-Kara / MMS 主对齐与备用时间轴均未生成完整结果。请使用任务 ID 查询日志。"
    ),
    "GENERATING_SUBTITLE": (
        "服务器未生成 Kirakara 字幕工程。请使用任务 ID 查询字幕日志。"
    ),
    "RENDERING_VIDEO": (
        "服务器未完成最终视频渲染。请使用任务 ID 查询渲染日志。"
    ),
}

FFMPEG_UNAVAILABLE_MESSAGE = (
    "服务器音视频处理工具不可用，请管理员检查 FFmpeg 安装和配置。"
)


class TranscriptionPipeline:
    def __init__(
        self,
        *,
        database: Database,
        extractor: Any,
        transcriber: Any,
        vocal_remover: Any | None = None,
        lyric_processor: Any | None = None,
        aligner: Any | None = None,
        subtitle_generator: Any | None = None,
        video_renderer: Any | None = None,
        event_logger: StructuredEventLogger | None = None,
    ) -> None:
        self.database = database
        self.extractor = extractor
        self.transcriber = transcriber
        self.vocal_remover = vocal_remover
        self.lyric_processor = lyric_processor
        self.aligner = aligner
        self.subtitle_generator = subtitle_generator
        self.video_renderer = video_renderer
        self.event_logger = (
            event_logger
            or database.event_logger
            or StructuredEventLogger(database=database)
        )

    def process(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job["status"] == "CANCELED":
            return

        inherited_context = current_event_context()
        run_id = str(inherited_context.get("run_id") or uuid4())
        pipeline_started = time.perf_counter()
        pipeline_error: BaseException | None = None
        was_canceled = False
        run_context = event_context(
            job_id=job_id,
            run_id=run_id,
            component="transcription_pipeline",
        )
        run_context.__enter__()
        self.event_logger.emit(
            event="pipeline.started",
            level="INFO",
            category="pipeline",
            message="任务处理流水线启动",
            details={
                "input_mode": job.get("input_mode", "VIDEO"),
                "vocal_mode": job.get("vocal_mode", "on"),
                "resumed_from_stage": job.get("stage"),
                "input_size_bytes": job.get("video_size_bytes"),
            },
        )

        video_path = Path(job["video_path"])
        job_dir = video_path.parent
        audio_path = job_dir / "audio.wav"
        vocals_path = job_dir / "audio_vocals.wav"
        instrumental_path = job_dir / "audio_instrumental.wav"
        transcript_path = job_dir / "transcript.json"
        lyrics_processed_path = job_dir / "lyrics_processed.json"
        timeline_path = job_dir / "timeline.json"
        ass_path = (
            Path(job["ass_path"])
            if job.get("ass_path")
            else job_dir / "lyrics.ass"
        )
        output_path = job_dir / "final_karaoke.mp4"

        stage = "EXTRACTING_AUDIO"
        resumed_stage: list[str] | None = None
        try:
            if job.get("stage") == "ALIGNMENT_QUEUED":
                resumed_stage = ["ALIGNING"]
                self._resume_reviewed_alignment(
                    job_id=job_id,
                    job=job,
                    video_path=video_path,
                    audio_path=audio_path,
                    vocals_path=vocals_path,
                    instrumental_path=instrumental_path,
                    transcript_path=transcript_path,
                    lyrics_processed_path=lyrics_processed_path,
                    timeline_path=timeline_path,
                    ass_path=ass_path,
                    output_path=output_path,
                    stage_state=resumed_stage,
                )
                return
            if job.get("stage") == "CLOUD_RENDER_QUEUED":
                stage = "RENDERING_VIDEO"
                if self.video_renderer is None or not ass_path.is_file():
                    raise RuntimeError("Kirakara cloud renderer is unavailable")
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=50,
                    timeline_path=timeline_path if timeline_path.exists() else None,
                    ass_path=ass_path,
                )
                vocal_mode = job.get("vocal_mode", "on")
                with self.event_logger.stage(
                    job_id=job_id,
                    run_id=run_id,
                    stage="RENDERING_VIDEO",
                    component="ffmpeg",
                    message="云端视频渲染",
                    details={
                        "render_mode": "cloud",
                        "input_size_bytes": self._file_size(video_path),
                        "ass_size_bytes": self._file_size(ass_path),
                        "preset": getattr(
                            self.video_renderer, "preset", None
                        ),
                        "crf": getattr(self.video_renderer, "crf", None),
                        "vocal_mode": vocal_mode,
                    },
                ) as render_trace:
                    self.video_renderer.render(
                        video_path,
                        ass_path,
                        output_path,
                        vocal_mode=vocal_mode,
                        instrumental_audio_path=(
                            instrumental_path
                            if vocal_mode == "off"
                            and instrumental_path.exists()
                            else None
                        ),
                    )
                    render_trace.result(
                        exit_code=0,
                        output_size_bytes=self._file_size(output_path),
                    )
                self.database.update_job_state(
                    job_id,
                    status="COMPLETED",
                    stage="VIDEO_RENDERING_COMPLETE",
                    progress=100,
                    timeline_path=timeline_path if timeline_path.exists() else None,
                    ass_path=ass_path,
                    output_path=output_path,
                )
                return

            self.database.update_job_state(
                job_id,
                status="PROCESSING",
                stage=stage,
                progress=15,
            )
            with self.event_logger.stage(
                job_id=job_id,
                run_id=run_id,
                stage="EXTRACTING_AUDIO",
                component="ffmpeg",
                message="音频提取",
                details={
                    "input_size_bytes": self._file_size(video_path),
                    "extractor": type(self.extractor).__name__,
                    "timeout_seconds": getattr(
                        self.extractor, "timeout_seconds", None
                    ),
                },
            ) as trace:
                self.extractor.extract(video_path, audio_path)
                trace.result(
                    output_size_bytes=self._file_size(audio_path),
                    output_format=audio_path.suffix.lower(),
                    exit_code=0,
                    **self._audio_summary(audio_path),
                )
            vocal_mode = job.get("vocal_mode", "on")
            lyrics_path_value = job.get("lyrics_path")
            render_vocal_mode = "on"
            direct_alignment_job = (
                job.get("input_mode", "VIDEO") == "AUDIO_ONLY"
                and bool(
                    getattr(
                        self.aligner,
                        "supports_transcriptless_alignment",
                        False,
                    )
                )
                and self.lyric_processor is not None
                and bool(lyrics_path_value)
            )
            alignment_fallback_warning: str | None = None
            alignment_requires_vocals = (
                direct_alignment_job
                and bool(getattr(self.aligner, "requires_vocals", False))
            )
            high_accuracy_audio_job = (
                alignment_requires_vocals
                and self.vocal_remover is not None
                and hasattr(self.vocal_remover, "separate_stems")
            )
            if alignment_requires_vocals and not high_accuracy_audio_job:
                direct_alignment_job = False
                alignment_fallback_warning = "uvr_unavailable"
            analysis_audio_path = audio_path
            if vocal_mode == "off" or high_accuracy_audio_job:
                stage = "REMOVING_VOCALS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=25,
                    audio_path=audio_path,
                )
                if self.vocal_remover is not None:
                    stereo_path = job_dir / "audio_stereo.wav"
                    self.extractor.extract_stereo(video_path, stereo_path)
                    try:
                        with self.event_logger.stage(
                            job_id=job_id,
                            run_id=run_id,
                            stage="REMOVING_VOCALS",
                            component="uvr",
                            message="人声与伴奏分离",
                            details={
                                "remover": type(
                                    self.vocal_remover
                                ).__name__,
                                "model": getattr(
                                    self.vocal_remover,
                                    "model_filename",
                                    None,
                                ),
                                "input_size_bytes": self._file_size(
                                    stereo_path
                                ),
                                "stem_mode": "both"
                                if high_accuracy_audio_job
                                else "instrumental",
                            },
                        ) as vocal_trace:
                            if high_accuracy_audio_job and hasattr(
                                self.vocal_remover,
                                "separate_stems",
                            ):
                                try:
                                    self.vocal_remover.separate_stems(
                                        stereo_path,
                                        vocals_path,
                                        instrumental_path,
                                    )
                                    analysis_audio_path = vocals_path
                                except Exception as exc:
                                    if vocal_mode == "off":
                                        raise
                                    vocals_path.unlink(missing_ok=True)
                                    instrumental_path.unlink(missing_ok=True)
                                    alignment_fallback_warning = (
                                        f"uvr_fallback:{type(exc).__name__}"
                                    )
                                    direct_alignment_job = False
                                    vocal_trace.fallback(
                                        reason=alignment_fallback_warning,
                                        selected_audio="original",
                                    )
                                    safe_error = exception_details(
                                        exc, include_traceback=False
                                    )
                                    logger.warning(
                                        "Vocal separation failed; using original "
                                        "audio and fallback alignment: %s: %s",
                                        safe_error["exception_type"],
                                        safe_error["error_summary"],
                                    )
                            else:
                                self.vocal_remover.remove_vocals(
                                    stereo_path, instrumental_path
                                )
                            vocal_trace.result(
                                vocals_size_bytes=self._file_size(
                                    vocals_path
                                ),
                                instrumental_size_bytes=self._file_size(
                                    instrumental_path
                                ),
                                selected_audio=(
                                    "vocals"
                                    if analysis_audio_path == vocals_path
                                    else "original"
                                ),
                            )
                    finally:
                        stereo_path.unlink(missing_ok=True)
                if vocal_mode == "off":
                    render_vocal_mode = "off"
            else:
                self.event_logger.emit(
                    event="stage.skipped",
                    level="INFO",
                    category="pipeline",
                    message="当前分支不需要人声与伴奏分离",
                    stage="REMOVING_VOCALS",
                    component="uvr",
                    details={
                        "reason": "on_vocal_without_direct_mms_requirement"
                    },
                )
            transcript = None

            def load_transcript():
                nonlocal transcript
                if transcript is None:
                    with self.event_logger.stage(
                        job_id=job_id,
                        run_id=run_id,
                        stage="TRANSCRIBING",
                        component="whisper",
                        message="歌声时间分析",
                        details={
                            "model": getattr(
                                self.transcriber, "model_name", None
                            ),
                            "device": getattr(
                                self.transcriber, "device", None
                            ),
                            "compute_type": getattr(
                                self.transcriber, "compute_type", None
                            ),
                            "input_size_bytes": self._file_size(
                                analysis_audio_path
                            ),
                        },
                    ) as trace:
                        transcript = self.transcriber.transcribe(
                            analysis_audio_path
                        )
                        transcript_path.write_text(
                            json.dumps(
                                transcript.to_dict(),
                                ensure_ascii=False,
                                indent=2,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        trace.result(
                            **self._transcript_summary(transcript),
                            output_size_bytes=self._file_size(
                                transcript_path
                            ),
                        )
                return transcript

            if not direct_alignment_job:
                stage = "TRANSCRIBING"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=40,
                    audio_path=audio_path,
                )
                load_transcript()
            else:
                self.event_logger.emit(
                    event="stage.skipped",
                    level="INFO",
                    category="pipeline",
                    message="高精度音频对齐路径暂不需要 Whisper 转录",
                    stage="TRANSCRIBING",
                    component="whisper",
                    details={"reason": "direct_fa_kara_alignment"},
                )
            if self.lyric_processor is not None and lyrics_path_value:
                stage = "PROCESSING_LYRICS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=75,
                    audio_path=audio_path,
                    transcript_path=(
                        transcript_path if transcript_path.exists() else None
                    ),
                )
                with self.event_logger.stage(
                    job_id=job_id,
                    run_id=run_id,
                    stage="PROCESSING_LYRICS",
                    component=self._lyric_component(),
                    message="歌词读取与注音处理",
                    details={
                        **self._lyric_processor_details(),
                        "input_size_bytes": self._file_size(
                            Path(lyrics_path_value)
                        ),
                    },
                ) as lyric_trace:
                    lyrics = Path(lyrics_path_value).read_text(encoding="utf-8")
                    parsed_lrc = parse_lrc(lyrics)
                    processed_lyrics = self.lyric_processor.process(
                        parsed_lrc.lyrics_text
                        if parsed_lrc.has_timing
                        else lyrics
                    )
                    lyrics_processed_path.write_text(
                        json.dumps(
                            processed_lyrics.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    lyric_trace.result(
                        **self._lyrics_summary(
                            lyrics,
                            processed_lyrics,
                            has_lrc_timing=parsed_lrc.has_timing,
                        ),
                        output_size_bytes=self._file_size(
                            lyrics_processed_path
                        ),
                    )
                    fallback_warnings = [
                        warning
                        for warning in processed_lyrics.warnings
                        if "fallback" in warning.lower()
                    ]
                    if fallback_warnings:
                        lyric_trace.fallback(
                            reason="; ".join(fallback_warnings),
                            fallback_processor="local",
                        )
                if self.aligner is not None:
                    if bool(
                        getattr(
                            self.aligner,
                            "requires_reading_review",
                            False,
                        )
                    ):
                        self.database.update_job_state(
                            job_id,
                            status="LYRICS_PROCESSED",
                            stage="READING_REVIEW_REQUIRED",
                            progress=80,
                            audio_path=audio_path,
                            transcript_path=(
                                transcript_path
                                if transcript_path.exists()
                                else None
                            ),
                            lyrics_processed_path=lyrics_processed_path,
                        )
                        return
                    stage = "ALIGNING"
                    self.database.update_job_state(
                        job_id,
                        status="PROCESSING",
                        stage=stage,
                        progress=90,
                        audio_path=audio_path,
                        transcript_path=(
                            transcript_path
                            if transcript_path.exists()
                            else None
                        ),
                        lyrics_processed_path=lyrics_processed_path,
                    )
                    with self.event_logger.stage(
                        job_id=job_id,
                    run_id=run_id,
                    stage="ALIGNING",
                    component=self._alignment_component(),
                        message="歌词时间轴对齐",
                        details={
                            **self._alignment_details(),
                            "direct_audio_alignment": direct_alignment_job,
                            "uses_lrc_timing": parsed_lrc.has_timing,
                            "audio_size_bytes": self._file_size(
                                analysis_audio_path
                            ),
                        },
                    ) as alignment_trace:
                        if direct_alignment_job:
                            timeline = self.aligner.align(
                                processed_lyrics,
                                None,
                                audio_path=analysis_audio_path,
                                transcript_factory=load_transcript,
                            )
                        else:
                            timeline = self.aligner.align(
                                processed_lyrics, transcript
                            )
                        if alignment_fallback_warning is not None:
                            timeline = replace(
                                timeline,
                                warnings=[
                                    *timeline.warnings,
                                    alignment_fallback_warning,
                                ],
                            )
                        if parsed_lrc.has_timing:
                            timeline = retime_timeline_from_lrc(
                                timeline,
                                parsed_lrc.line_starts_ms,
                            )
                        fallback_warnings = [
                            warning
                            for warning in timeline.warnings
                            if "fallback" in warning.lower()
                            or "unavailable" in warning.lower()
                        ]
                        if fallback_warnings:
                            alignment_trace.fallback(
                                reason="; ".join(fallback_warnings),
                                selected_engine=timeline.alignment_engine,
                            )
                        alignment_trace.result(
                            **self._timeline_summary(timeline)
                        )
                    timeline_path.write_text(
                        json.dumps(
                            timeline.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    if self.subtitle_generator is not None:
                        stage = "GENERATING_SUBTITLE"
                        self.database.update_job_state(
                            job_id,
                            status="PROCESSING",
                            stage=stage,
                            progress=95,
                            audio_path=audio_path,
                            transcript_path=(
                                transcript_path
                                if transcript_path.exists()
                                else None
                            ),
                            lyrics_processed_path=lyrics_processed_path,
                            timeline_path=timeline_path,
                        )
                        with self.event_logger.stage(
                            job_id=job_id,
                            run_id=run_id,
                            stage="GENERATING_SUBTITLE",
                            component=type(self.subtitle_generator).__name__,
                            message="ASS 字幕生成",
                            details={
                                "timeline_lines": len(timeline.lines),
                                "generator": type(
                                    self.subtitle_generator
                                ).__name__,
                            },
                        ) as subtitle_trace:
                            ass_content = self.subtitle_generator.generate(
                                timeline
                            )
                            ass_path.write_text(
                                ass_content,
                                encoding="utf-8-sig",
                            )
                            subtitle_trace.result(
                                ass_event_count=self._ass_event_count(
                                    ass_content
                                ),
                                output_size_bytes=self._file_size(ass_path),
                            )
                        if (
                            self.video_renderer is not None
                            and job.get("input_mode", "VIDEO") != "AUDIO_ONLY"
                        ):
                            stage = "RENDERING_VIDEO"
                            self.database.update_job_state(
                                job_id,
                                status="PROCESSING",
                                stage=stage,
                                progress=98,
                                audio_path=audio_path,
                                transcript_path=(
                                    transcript_path
                                    if transcript_path.exists()
                                    else None
                                ),
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                            with self.event_logger.stage(
                                job_id=job_id,
                                run_id=run_id,
                                stage="RENDERING_VIDEO",
                                component="ffmpeg",
                                message="视频渲染",
                                details={
                                    "input_size_bytes": self._file_size(
                                        video_path
                                    ),
                                    "ass_size_bytes": self._file_size(
                                        ass_path
                                    ),
                                    "preset": getattr(
                                        self.video_renderer, "preset", None
                                    ),
                                    "crf": getattr(
                                        self.video_renderer, "crf", None
                                    ),
                                    "vocal_mode": render_vocal_mode,
                                },
                            ) as render_trace:
                                self.video_renderer.render(
                                    video_path,
                                    ass_path,
                                    output_path,
                                    vocal_mode=render_vocal_mode,
                                    instrumental_audio_path=instrumental_path if render_vocal_mode == "off" and instrumental_path.exists() else None,
                                )
                                render_trace.result(
                                    exit_code=0,
                                    output_size_bytes=self._file_size(
                                        output_path
                                    ),
                                )
                            self.database.update_job_state(
                                job_id,
                                status="COMPLETED",
                                stage="VIDEO_RENDERING_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=(
                                    transcript_path
                                    if transcript_path.exists()
                                    else None
                                ),
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                                output_path=output_path,
                            )
                        else:
                            self.event_logger.emit(
                                event="stage.skipped",
                                level="INFO",
                                category="pipeline",
                                message="音频任务不需要云端视频渲染",
                                stage="RENDERING_VIDEO",
                                component="ffmpeg",
                                details={
                                    "reason": "audio_only_or_renderer_disabled"
                                },
                            )
                            self.database.update_job_state(
                                job_id,
                                status="SUBTITLE_GENERATED",
                                stage="SUBTITLE_GENERATION_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=(
                                    transcript_path
                                    if transcript_path.exists()
                                    else None
                                ),
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                    else:
                        self.database.update_job_state(
                            job_id,
                            status="ALIGNED",
                            stage="ALIGNMENT_COMPLETE",
                            progress=100,
                            audio_path=audio_path,
                            transcript_path=(
                                transcript_path
                                if transcript_path.exists()
                                else None
                            ),
                            lyrics_processed_path=lyrics_processed_path,
                            timeline_path=timeline_path,
                        )
                else:
                    self.database.update_job_state(
                        job_id,
                        status="LYRICS_PROCESSED",
                        stage="LYRIC_PROCESSING_COMPLETE",
                        progress=100,
                        audio_path=audio_path,
                        transcript_path=(
                            transcript_path
                            if transcript_path.exists()
                            else None
                        ),
                        lyrics_processed_path=lyrics_processed_path,
                    )
            else:
                self.event_logger.emit(
                    event="stage.skipped",
                    level="INFO",
                    category="pipeline",
                    message="任务未提供歌词，跳过歌词处理与对齐",
                    stage="PROCESSING_LYRICS",
                    component="lyrics",
                    details={"reason": "lyrics_not_provided"},
                )
                self.database.update_job_state(
                    job_id,
                    status="TRANSCRIBED",
                    stage="TRANSCRIPTION_COMPLETE",
                    progress=100,
                    audio_path=audio_path,
                    transcript_path=(
                        transcript_path if transcript_path.exists() else None
                    ),
                )
        except JobCanceledError:
            was_canceled = True
            logger.info("Job %s stopped after user cancellation", job_id)
            return
        except Exception as exc:
            pipeline_error = exc
            if resumed_stage is not None:
                stage = resumed_stage[0]
            safe_error = exception_details(exc, include_traceback=False)
            logger.error(
                "Job %s failed during stage %s (%s: %s)",
                job_id,
                stage,
                safe_error["exception_type"],
                safe_error["error_summary"],
            )
            error_code = (
                "FFMPEG_UNAVAILABLE"
                if isinstance(exc, FFmpegUnavailableError)
                else {
                "REMOVING_VOCALS": "VOCAL_REMOVAL_FAILED",
                "EXTRACTING_AUDIO": "AUDIO_EXTRACTION_FAILED",
                "TRANSCRIBING": "TRANSCRIPTION_FAILED",
                "PROCESSING_LYRICS": "LYRIC_PROCESSING_FAILED",
                "ALIGNING": "ALIGNMENT_FAILED",
                "GENERATING_SUBTITLE": "SUBTITLE_GENERATION_FAILED",
                "RENDERING_VIDEO": "VIDEO_RENDERING_FAILED",
                }[stage]
            )
            progress = {
                "REMOVING_VOCALS": 25,
                "EXTRACTING_AUDIO": 15,
                "TRANSCRIBING": 40,
                "PROCESSING_LYRICS": 75,
                "ALIGNING": 90,
                "GENERATING_SUBTITLE": 95,
                "RENDERING_VIDEO": 98,
            }[stage]
            self.database.update_job_state(
                job_id,
                status="FAILED",
                stage=stage,
                progress=progress,
                audio_path=audio_path if audio_path.exists() else None,
                transcript_path=(
                    transcript_path if transcript_path.exists() else None
                ),
                lyrics_processed_path=(
                    lyrics_processed_path
                    if lyrics_processed_path.exists()
                    else None
                ),
                timeline_path=(
                    timeline_path if timeline_path.exists() else None
                ),
                ass_path=ass_path if ass_path.exists() else None,
                output_path=(
                    output_path if output_path.exists() else None
                ),
                error_code=error_code,
                error_message=(
                    FFMPEG_UNAVAILABLE_MESSAGE
                    if error_code == "FFMPEG_UNAVAILABLE"
                    else PUBLIC_ERROR_MESSAGES[stage]
                ),
            )
            raise
        finally:
            final_job = self.database.get_job(job_id)
            duration_ms = (time.perf_counter() - pipeline_started) * 1000
            if pipeline_error is not None:
                self.event_logger.emit(
                    event="pipeline.failed",
                    level="ERROR",
                    category="pipeline",
                    message="任务处理流水线失败",
                    stage=stage,
                    duration_ms=duration_ms,
                    details={
                        "error_code": (
                            final_job.get("error_code") if final_job else None
                        ),
                        **exception_details(pipeline_error),
                    },
                )
            elif was_canceled or (
                final_job is not None
                and final_job.get("status") == "CANCELED"
            ):
                self.event_logger.emit(
                    event="pipeline.canceled",
                    level="WARNING",
                    category="pipeline",
                    message="任务处理流水线已取消",
                    stage=final_job.get("stage") if final_job else stage,
                    duration_ms=duration_ms,
                )
            elif (
                final_job is not None
                and final_job.get("stage") == "READING_REVIEW_REQUIRED"
            ):
                self.event_logger.emit(
                    event="pipeline.paused",
                    level="INFO",
                    category="pipeline",
                    message="流水线暂停，等待用户确认注音",
                    stage="READING_REVIEW_REQUIRED",
                    duration_ms=duration_ms,
                )
            else:
                self.event_logger.emit(
                    event="pipeline.completed",
                    level="INFO",
                    category="pipeline",
                    message="任务处理流水线完成",
                    stage=final_job.get("stage") if final_job else stage,
                    duration_ms=duration_ms,
                    details={
                        "status": final_job.get("status")
                        if final_job
                        else None,
                        "output_size_bytes": self._file_size(output_path),
                    },
                )
            run_context.__exit__(None, None, None)

    @staticmethod
    def _file_size(path: Path) -> int | None:
        try:
            return path.stat().st_size if path.is_file() else None
        except OSError:
            return None

    @staticmethod
    def _audio_summary(path: Path) -> dict[str, Any]:
        try:
            with wave.open(str(path), "rb") as audio:
                sample_rate = audio.getframerate()
                frame_count = audio.getnframes()
                return {
                    "sample_rate_hz": sample_rate,
                    "channel_count": audio.getnchannels(),
                    "duration_seconds": (
                        frame_count / sample_rate if sample_rate else None
                    ),
                }
        except (OSError, EOFError, wave.Error):
            return {}

    @staticmethod
    def _transcript_summary(transcript: Any) -> dict[str, Any]:
        segments = list(getattr(transcript, "segments", []) or [])
        return {
            "language": getattr(transcript, "language", None),
            "language_confidence": getattr(
                transcript, "language_probability", None
            ),
            "duration_seconds": getattr(
                transcript, "duration_seconds", None
            ),
            "segment_count": len(segments),
            "word_count": sum(
                len(getattr(segment, "words", []) or [])
                for segment in segments
            ),
        }

    @staticmethod
    def _lyrics_summary(
        raw_lyrics: str,
        processed_lyrics: Any,
        *,
        has_lrc_timing: bool,
    ) -> dict[str, Any]:
        return {
            "source_line_count": len(raw_lyrics.splitlines()),
            "source_character_count": len(raw_lyrics),
            "processed_line_count": len(
                getattr(processed_lyrics, "lines", []) or []
            ),
            "has_lrc_timing": has_lrc_timing,
            "provider": getattr(processed_lyrics, "provider", None),
            "warning_count": len(
                getattr(processed_lyrics, "warnings", []) or []
            ),
        }

    @staticmethod
    def _timeline_summary(timeline: Any) -> dict[str, Any]:
        lines = list(getattr(timeline, "lines", []) or [])
        confidences = [
            float(getattr(line, "confidence", 0.0)) for line in lines
        ]
        return {
            "alignment_engine": getattr(
                timeline, "alignment_engine", None
            ),
            "alignment_model": getattr(timeline, "alignment_model", None),
            "line_count": len(lines),
            "confidence": getattr(timeline, "confidence", None),
            "minimum_line_confidence": min(confidences)
            if confidences
            else None,
            "warning_count": len(
                getattr(timeline, "warnings", []) or []
            ),
            "warnings": list(getattr(timeline, "warnings", []) or []),
        }

    @staticmethod
    def _ass_event_count(content: str) -> int:
        return sum(
            1 for line in content.splitlines() if line.startswith("Dialogue:")
        )

    def _lyric_component(self) -> str:
        primary = getattr(self.lyric_processor, "primary", None)
        return "deepseek" if primary is not None else type(
            self.lyric_processor
        ).__name__

    def _lyric_processor_details(self) -> dict[str, Any]:
        primary = getattr(self.lyric_processor, "primary", None)
        fallback = getattr(self.lyric_processor, "fallback", None)
        client = getattr(primary, "client", None)
        return {
            "processor": type(self.lyric_processor).__name__,
            "primary_processor": type(primary).__name__
            if primary is not None
            else None,
            "fallback_processor": type(fallback).__name__
            if fallback is not None
            else None,
            "model": getattr(client, "model", None),
            "timeout_seconds": getattr(client, "timeout_seconds", None),
        }

    def _alignment_component(self) -> str:
        return "fa_kara" if getattr(self.aligner, "primary", None) else type(
            self.aligner
        ).__name__

    def _alignment_details(self) -> dict[str, Any]:
        primary = getattr(self.aligner, "primary", None)
        fallback = getattr(self.aligner, "fallback", None)
        runtime = getattr(primary, "runtime", None)
        return {
            "aligner": type(self.aligner).__name__,
            "primary_aligner": type(primary).__name__
            if primary is not None
            else None,
            "fallback_aligner": type(fallback).__name__
            if fallback is not None
            else None,
            "model": "torchaudio.pipelines.MMS_FA"
            if primary is not None
            else None,
            "device": getattr(runtime, "device", None),
            "timeout_seconds": getattr(primary, "timeout_seconds", None),
            "minimum_confidence": getattr(
                primary, "min_confidence", None
            ),
        }

    def _resume_reviewed_alignment(
        self,
        *,
        job_id: str,
        job: dict[str, Any],
        video_path: Path,
        audio_path: Path,
        vocals_path: Path,
        instrumental_path: Path,
        transcript_path: Path,
        lyrics_processed_path: Path,
        timeline_path: Path,
        ass_path: Path,
        output_path: Path,
        stage_state: list[str],
    ) -> None:
        run_id = str(current_event_context().get("run_id") or uuid4())
        if self.aligner is None:
            raise RuntimeError("Lyric alignment is unavailable")
        if not audio_path.is_file() or not lyrics_processed_path.is_file():
            raise RuntimeError("Reading review artifacts are incomplete")

        processed_lyrics = lyric_document_from_dict(
            json.loads(lyrics_processed_path.read_text(encoding="utf-8"))
        )
        lyrics_path_value = job.get("lyrics_path")
        parsed_lrc = parse_lrc(
            Path(lyrics_path_value).read_text(encoding="utf-8")
            if lyrics_path_value
            else processed_lyrics.source_text
        )
        transcript = (
            transcript_document_from_dict(
                json.loads(transcript_path.read_text(encoding="utf-8"))
            )
            if transcript_path.is_file()
            else None
        )
        direct_alignment_job = (
            job.get("input_mode", "VIDEO") == "AUDIO_ONLY"
            and bool(
                getattr(
                    self.aligner,
                    "supports_transcriptless_alignment",
                    False,
                )
            )
        )
        alignment_requires_vocals = bool(
            getattr(self.aligner, "requires_vocals", False)
        )
        alignment_fallback_warning: str | None = None
        analysis_audio_path = audio_path
        if alignment_requires_vocals:
            if vocals_path.is_file():
                analysis_audio_path = vocals_path
            else:
                direct_alignment_job = False
                alignment_fallback_warning = "uvr_unavailable"

        def load_transcript():
            nonlocal transcript
            if transcript is None:
                with self.event_logger.stage(
                    job_id=job_id,
                    run_id=run_id,
                    stage="TRANSCRIBING",
                    component="whisper",
                    message="恢复流程中的歌声时间分析",
                    details={
                        "resume_after_reading_review": True,
                        "model": getattr(
                            self.transcriber, "model_name", None
                        ),
                        "device": getattr(self.transcriber, "device", None),
                    },
                ) as trace:
                    transcript = self.transcriber.transcribe(
                        analysis_audio_path
                    )
                    transcript_path.write_text(
                        json.dumps(
                            transcript.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    trace.result(**self._transcript_summary(transcript))
            return transcript

        self.database.update_job_state(
            job_id,
            status="PROCESSING",
            stage="ALIGNING",
            progress=90,
            audio_path=audio_path,
            transcript_path=(
                transcript_path if transcript_path.exists() else None
            ),
            lyrics_processed_path=lyrics_processed_path,
        )
        with self.event_logger.stage(
            job_id=job_id,
            run_id=run_id,
            stage="ALIGNING",
            component=self._alignment_component(),
            message="确认注音后的歌词时间轴对齐",
            details={
                "resume_after_reading_review": True,
                **self._alignment_details(),
                "direct_audio_alignment": direct_alignment_job,
                "uses_lrc_timing": parsed_lrc.has_timing,
            },
        ) as alignment_trace:
            if direct_alignment_job:
                timeline = self.aligner.align(
                    processed_lyrics,
                    None,
                    audio_path=analysis_audio_path,
                    transcript_factory=load_transcript,
                )
            else:
                timeline = self.aligner.align(
                    processed_lyrics,
                    load_transcript(),
                )
            if alignment_fallback_warning is not None:
                timeline = replace(
                    timeline,
                    warnings=[
                        *timeline.warnings,
                        alignment_fallback_warning,
                    ],
                )
                alignment_trace.fallback(
                    reason=alignment_fallback_warning,
                    selected_engine=timeline.alignment_engine,
                )
            if parsed_lrc.has_timing:
                timeline = retime_timeline_from_lrc(
                    timeline,
                    parsed_lrc.line_starts_ms,
                )
            timeline_path.write_text(
                json.dumps(
                    timeline.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            alignment_trace.result(**self._timeline_summary(timeline))

        if self.subtitle_generator is None:
            self.database.update_job_state(
                job_id,
                status="ALIGNED",
                stage="ALIGNMENT_COMPLETE",
                progress=100,
                audio_path=audio_path,
                transcript_path=(
                    transcript_path if transcript_path.exists() else None
                ),
                lyrics_processed_path=lyrics_processed_path,
                timeline_path=timeline_path,
            )
            return

        stage_state[0] = "GENERATING_SUBTITLE"
        self.database.update_job_state(
            job_id,
            status="PROCESSING",
            stage="GENERATING_SUBTITLE",
            progress=95,
            audio_path=audio_path,
            transcript_path=(
                transcript_path if transcript_path.exists() else None
            ),
            lyrics_processed_path=lyrics_processed_path,
            timeline_path=timeline_path,
        )
        with self.event_logger.stage(
            job_id=job_id,
            run_id=run_id,
            stage="GENERATING_SUBTITLE",
            component=type(self.subtitle_generator).__name__,
            message="确认注音后的 ASS 字幕生成",
            details={"timeline_lines": len(timeline.lines)},
        ) as subtitle_trace:
            ass_content = self.subtitle_generator.generate(timeline)
            ass_path.write_text(ass_content, encoding="utf-8-sig")
            subtitle_trace.result(
                ass_event_count=self._ass_event_count(ass_content),
                output_size_bytes=self._file_size(ass_path),
            )
        if (
            self.video_renderer is None
            or job.get("input_mode", "VIDEO") == "AUDIO_ONLY"
        ):
            self.database.update_job_state(
                job_id,
                status="SUBTITLE_GENERATED",
                stage="SUBTITLE_GENERATION_COMPLETE",
                progress=100,
                audio_path=audio_path,
                transcript_path=(
                    transcript_path if transcript_path.exists() else None
                ),
                lyrics_processed_path=lyrics_processed_path,
                timeline_path=timeline_path,
                ass_path=ass_path,
            )
            return

        stage_state[0] = "RENDERING_VIDEO"
        self.database.update_job_state(
            job_id,
            status="PROCESSING",
            stage="RENDERING_VIDEO",
            progress=98,
            audio_path=audio_path,
            transcript_path=(
                transcript_path if transcript_path.exists() else None
            ),
            lyrics_processed_path=lyrics_processed_path,
            timeline_path=timeline_path,
            ass_path=ass_path,
        )
        render_vocal_mode = (
            "off" if job.get("vocal_mode", "on") == "off" else "on"
        )
        with self.event_logger.stage(
            job_id=job_id,
            run_id=run_id,
            stage="RENDERING_VIDEO",
            component="ffmpeg",
            message="确认注音后的视频渲染",
            details={
                "preset": getattr(self.video_renderer, "preset", None),
                "crf": getattr(self.video_renderer, "crf", None),
                "vocal_mode": render_vocal_mode,
            },
        ) as render_trace:
            self.video_renderer.render(
                video_path,
                ass_path,
                output_path,
                vocal_mode=render_vocal_mode,
                instrumental_audio_path=(
                    instrumental_path
                    if render_vocal_mode == "off"
                    and instrumental_path.exists()
                    else None
                ),
            )
            render_trace.result(
                exit_code=0,
                output_size_bytes=self._file_size(output_path),
            )
        self.database.update_job_state(
            job_id,
            status="COMPLETED",
            stage="VIDEO_RENDERING_COMPLETE",
            progress=100,
            audio_path=audio_path,
            transcript_path=(
                transcript_path if transcript_path.exists() else None
            ),
            lyrics_processed_path=lyrics_processed_path,
            timeline_path=timeline_path,
            ass_path=ass_path,
            output_path=output_path,
        )
