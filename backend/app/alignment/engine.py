from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.ai.whisper import TranscriptDocument
from app.alignment.models import LyricTimeline
from app.lyrics.models import LyricDocument


logger = logging.getLogger(__name__)


class ResilientAlignmentEngine:
    """Use audio forced alignment when available and preserve the old fallback."""

    requires_vocals = True

    def __init__(self, *, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument,
        *,
        audio_path: Path | None = None,
    ) -> LyricTimeline:
        if audio_path is None:
            return self.fallback.align(lyrics, transcript)
        try:
            return self.primary.align(
                lyrics,
                transcript,
                audio_path=audio_path,
            )
        except Exception as exc:
            logger.warning(
                "High-accuracy alignment failed; using Whisper fallback: %s",
                type(exc).__name__,
            )
            timeline = self.fallback.align(lyrics, transcript)
            return replace(
                timeline,
                warnings=[
                    *timeline.warnings,
                    f"fa_kara_fallback:{type(exc).__name__}",
                ],
            )
