from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.database import Database, JobCanceledError


logger = logging.getLogger(__name__)

PUBLIC_ERROR_MESSAGES = {
    "REMOVING_VOCALS": (
        "Processing failed during vocal removal. "
        "Check server logs with this job ID."
    ),
    "EXTRACTING_AUDIO": (
        "Processing failed during audio extraction. "
        "Check server logs with this job ID."
    ),
    "TRANSCRIBING": (
        "Processing failed during audio transcription. "
        "Check server logs with this job ID."
    ),
    "PROCESSING_LYRICS": (
        "Processing failed during lyric processing. "
        "Check server logs with this job ID."
    ),
    "ALIGNING": (
        "Processing failed during lyric alignment. "
        "Check server logs with this job ID."
    ),
    "GENERATING_SUBTITLE": (
        "Processing failed during subtitle generation. "
        "Check server logs with this job ID."
    ),
    "RENDERING_VIDEO": (
        "Processing failed during video rendering. "
        "Check server logs with this job ID."
    ),
}


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
    ) -> None:
        self.database = database
        self.extractor = extractor
        self.transcriber = transcriber
        self.vocal_remover = vocal_remover
        self.lyric_processor = lyric_processor
        self.aligner = aligner
        self.subtitle_generator = subtitle_generator
        self.video_renderer = video_renderer

    def process(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job["status"] == "CANCELED":
            return

        video_path = Path(job["video_path"])
        job_dir = video_path.parent
        audio_path = job_dir / "audio.wav"
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
        try:
            if job.get("stage") == "CLOUD_RENDER_QUEUED":
                stage = "RENDERING_VIDEO"
                if self.video_renderer is None or not ass_path.is_file():
                    raise RuntimeError("Kirakara cloud renderer is unavailable")
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=98,
                    timeline_path=timeline_path if timeline_path.exists() else None,
                    ass_path=ass_path,
                )
                vocal_mode = job.get("vocal_mode", "on")
                self.video_renderer.render(
                    video_path,
                    ass_path,
                    output_path,
                    vocal_mode=vocal_mode,
                    instrumental_audio_path=(
                        instrumental_path
                        if vocal_mode == "off" and instrumental_path.exists()
                        else None
                    ),
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
            self.extractor.extract(video_path, audio_path)
            vocal_mode = job.get("vocal_mode", "on")
            render_vocal_mode = "on"
            if vocal_mode == "off":
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
                    self.vocal_remover.remove_vocals(
                        stereo_path, instrumental_path
                    )
                    stereo_path.unlink(missing_ok=True)
                render_vocal_mode = "off"
            stage = "TRANSCRIBING"
            self.database.update_job_state(
                job_id,
                status="PROCESSING",
                stage=stage,
                progress=40,
                audio_path=audio_path,
            )
            transcript = self.transcriber.transcribe(audio_path)
            transcript_path.write_text(
                json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            lyrics_path_value = job.get("lyrics_path")
            if self.lyric_processor is not None and lyrics_path_value:
                stage = "PROCESSING_LYRICS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=75,
                    audio_path=audio_path,
                    transcript_path=transcript_path,
                )
                lyrics = Path(lyrics_path_value).read_text(encoding="utf-8")
                processed_lyrics = self.lyric_processor.process(lyrics)
                lyrics_processed_path.write_text(
                    json.dumps(
                        processed_lyrics.to_dict(),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if self.aligner is not None:
                    stage = "ALIGNING"
                    self.database.update_job_state(
                        job_id,
                        status="PROCESSING",
                        stage=stage,
                        progress=90,
                        audio_path=audio_path,
                        transcript_path=transcript_path,
                        lyrics_processed_path=lyrics_processed_path,
                    )
                    timeline = self.aligner.align(processed_lyrics, transcript)
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
                            transcript_path=transcript_path,
                            lyrics_processed_path=lyrics_processed_path,
                            timeline_path=timeline_path,
                        )
                        ass_content = self.subtitle_generator.generate(timeline)
                        ass_path.write_text(
                            ass_content,
                            encoding="utf-8-sig",
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
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                            self.video_renderer.render(
                                video_path,
                                ass_path,
                                output_path,
                                vocal_mode=render_vocal_mode,
                                instrumental_audio_path=instrumental_path if render_vocal_mode == "off" and instrumental_path.exists() else None,
                            )
                            self.database.update_job_state(
                                job_id,
                                status="COMPLETED",
                                stage="VIDEO_RENDERING_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                                output_path=output_path,
                            )
                        else:
                            self.database.update_job_state(
                                job_id,
                                status="SUBTITLE_GENERATED",
                                stage="SUBTITLE_GENERATION_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
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
                            transcript_path=transcript_path,
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
                        transcript_path=transcript_path,
                        lyrics_processed_path=lyrics_processed_path,
                    )
            else:
                self.database.update_job_state(
                    job_id,
                    status="TRANSCRIBED",
                    stage="TRANSCRIPTION_COMPLETE",
                    progress=100,
                    audio_path=audio_path,
                    transcript_path=transcript_path,
                )
        except JobCanceledError:
            logger.info("Job %s stopped after user cancellation", job_id)
            return
        except Exception as exc:
            logger.exception(
                "Job %s failed during stage %s",
                job_id,
                stage,
            )
            error_code = {
                "REMOVING_VOCALS": "VOCAL_REMOVAL_FAILED",
                "EXTRACTING_AUDIO": "AUDIO_EXTRACTION_FAILED",
                "TRANSCRIBING": "TRANSCRIPTION_FAILED",
                "PROCESSING_LYRICS": "LYRIC_PROCESSING_FAILED",
                "ALIGNING": "ALIGNMENT_FAILED",
                "GENERATING_SUBTITLE": "SUBTITLE_GENERATION_FAILED",
                "RENDERING_VIDEO": "VIDEO_RENDERING_FAILED",
            }[stage]
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
                error_message=PUBLIC_ERROR_MESSAGES[stage],
            )
            raise
