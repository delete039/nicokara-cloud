from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from app.ai.whisper import TranscriptDocument
from app.alignment.models import LyricTimeline
from app.lyrics.models import LyricDocument
from app.core.event_logging import exception_details


logger = logging.getLogger(__name__)


class ResilientAlignmentEngine:
    """Use audio forced alignment when available and preserve the old fallback."""

    requires_vocals = True
    requires_reading_review = True
    supports_transcriptless_alignment = True

    def __init__(
        self,
        *,
        primary: Any,
        fallback: Any,
        event_logger: Any | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.event_logger = event_logger

    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument | None,
        *,
        audio_path: Path | None = None,
        transcript_factory: Callable[[], TranscriptDocument] | None = None,
    ) -> LyricTimeline:
        if audio_path is None:
            if transcript is None:
                if transcript_factory is None:
                    raise ValueError(
                        "A transcript is required when audio is unavailable"
                    )
                transcript = transcript_factory()
            return self.fallback.align(lyrics, transcript)
        try:
            return self.primary.align(
                lyrics,
                transcript,
                audio_path=audio_path,
            )
        except Exception as exc:
            safe_error = exception_details(exc, include_traceback=False)
            if self.event_logger is not None:
                self.event_logger.emit(
                    event="external.failed",
                    level="WARNING",
                    category="external",
                    message="FA-Kara/MMS 高精度对齐失败，将使用普通对齐器",
                    component="fa_kara",
                    details={
                        "fallback_component": type(self.fallback).__name__,
                        **exception_details(exc),
                    },
                )
            logger.warning(
                "High-accuracy alignment failed; using Whisper fallback: "
                "%s: %s",
                safe_error["exception_type"],
                safe_error["error_summary"],
            )
            if transcript is None:
                if transcript_factory is None:
                    raise
                transcript = transcript_factory()
            timeline = self.fallback.align(lyrics, transcript)
            return replace(
                timeline,
                warnings=[
                    *timeline.warnings,
                    f"fa_kara_fallback:{type(exc).__name__}",
                ],
            )
