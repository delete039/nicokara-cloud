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

    # The preferred Yohane path is more accurate on the original mix than on
    # a lossy MDX vocal stem; individual aligners still validate their input.
    requires_vocals = False
    requires_reading_review = True
    supports_transcriptless_alignment = True
    supports_alignment_modes = True

    def __init__(
        self,
        *,
        primary: Any,
        fallback: Any,
        multivoice_primary: Any | None = None,
        robust_primary: Any | None = None,
        event_logger: Any | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.multivoice_primary = multivoice_primary
        self.robust_primary = robust_primary
        self.event_logger = event_logger

    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument | None,
        *,
        audio_path: Path | None = None,
        transcript_factory: Callable[[], TranscriptDocument] | None = None,
        alignment_mode: str = "auto",
    ) -> LyricTimeline:
        if audio_path is None:
            if transcript is None:
                if transcript_factory is None:
                    raise ValueError(
                        "A transcript is required when audio is unavailable"
                    )
                transcript = transcript_factory()
            return self.fallback.align(lyrics, transcript)
        selected = self.primary
        selected_label = "standard high-accuracy"
        selected_warning = None
        if alignment_mode == "auto" and self.multivoice_primary is not None:
            selected = self.multivoice_primary
            selected_label = "yohane preferred"
            selected_warning = "auto_yohane_quality_fallback"
        elif alignment_mode == "multivoice" and self.multivoice_primary is not None:
            selected = self.multivoice_primary
            selected_label = "multivoice"
            selected_warning = "multivoice_yohane_quality_fallback"
        elif alignment_mode == "robust" and self.robust_primary is not None:
            selected = self.robust_primary
            selected_label = "robust dual"
            selected_warning = "robust_dual_quality_fallback"
        try:
            return selected.align(
                lyrics,
                transcript,
                audio_path=audio_path,
            )
        except Exception as exc:
            if selected is not self.primary:
                logger.warning(
                    "%s alignment failed; retrying with standard high-accuracy alignment: %s",
                    selected_label,
                    type(exc).__name__,
                )
                try:
                    timeline = self.primary.align(
                        lyrics,
                        transcript,
                        audio_path=audio_path,
                    )
                    return replace(
                        timeline,
                        warnings=[
                            *timeline.warnings,
                            selected_warning or "alignment_mode_quality_fallback",
                        ],
                    )
                except Exception as primary_exc:
                    exc = primary_exc
            safe_error = exception_details(exc, include_traceback=False)
            if self.event_logger is not None:
                self.event_logger.emit(
                    event="external.failed",
                    level="WARNING",
                    category="external",
                    message="高精度时间轴对齐失败，将使用普通对齐器",
                    component="fa_kara",
                    details={
                        "alignment_mode": alignment_mode,
                        "selected_component": type(selected).__name__,
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
