from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

from app.alignment.models import AlignedLine, LyricTimeline


ROBUST_DUAL_MAX_LINE_SHIFT_MS = 6_000
ROBUST_DUAL_MAX_GLOBAL_SHIFT_MS = 1_500
ROBUST_DUAL_MAX_MORA_DURATION_MS = 8_000
ROBUST_DUAL_MIN_CONFIDENCE = 0.10
ROBUST_DUAL_CONFIDENCE_MARGIN = 0.02
ROBUST_DUAL_MODEL_NAME = (
    "MMS_FA + NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
)


class RobustDualAlignment:
    """Keep MMS as the anchor and accept only bounded Yohane line fixes."""

    requires_vocals = True
    alignment_model = ROBUST_DUAL_MODEL_NAME

    def __init__(
        self,
        *,
        primary: Any,
        secondary: Any,
        max_line_shift_ms: int = ROBUST_DUAL_MAX_LINE_SHIFT_MS,
        min_confidence: float = ROBUST_DUAL_MIN_CONFIDENCE,
        confidence_margin: float = ROBUST_DUAL_CONFIDENCE_MARGIN,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self.max_line_shift_ms = max_line_shift_ms
        self.min_confidence = min_confidence
        self.confidence_margin = confidence_margin

    def align(
        self,
        lyrics,
        transcript,
        *,
        audio_path: Path,
    ) -> LyricTimeline:
        primary_timeline = self.primary.align(
            lyrics,
            transcript,
            audio_path=audio_path,
        )
        try:
            secondary_timeline = self.secondary.align(
                lyrics,
                transcript,
                audio_path=audio_path,
            )
        except Exception:
            return replace(
                primary_timeline,
                alignment_engine="fa_kara_robust_dual",
                alignment_model=ROBUST_DUAL_MODEL_NAME,
                warnings=[
                    *primary_timeline.warnings,
                    "robust_dual_mms_prior",
                    "robust_dual_yohane_fallback",
                ],
            )

        chosen_lines: list[AlignedLine] = []
        rejected = False
        if len(primary_timeline.lines) != len(secondary_timeline.lines):
            rejected = True
            chosen_lines = list(primary_timeline.lines)
        elif self._has_systematic_global_shift(
            primary_timeline,
            secondary_timeline,
        ):
            return replace(
                primary_timeline,
                alignment_engine="fa_kara_robust_dual",
                alignment_model=ROBUST_DUAL_MODEL_NAME,
                warnings=[
                    *primary_timeline.warnings,
                    "robust_dual_mms_prior",
                    "robust_dual_global_guard",
                ],
            )
        else:
            for primary_line, secondary_line in zip(
                primary_timeline.lines,
                secondary_timeline.lines,
                strict=True,
            ):
                if self._safe_candidate(primary_line, secondary_line):
                    chosen_lines.append(secondary_line)
                else:
                    chosen_lines.append(primary_line)
                    rejected = True

        confidence = (
            sum(line.confidence for line in chosen_lines) / len(chosen_lines)
            if chosen_lines
            else primary_timeline.confidence
        )
        warnings = [*primary_timeline.warnings, "robust_dual_mms_prior"]
        if rejected:
            warnings.append("robust_dual_rejected_candidate")
        return replace(
            primary_timeline,
            confidence=confidence,
            lines=chosen_lines,
            warnings=warnings,
            alignment_engine="fa_kara_robust_dual",
            alignment_model=ROBUST_DUAL_MODEL_NAME,
        )

    @staticmethod
    def _has_systematic_global_shift(
        primary_timeline: LyricTimeline,
        secondary_timeline: LyricTimeline,
    ) -> bool:
        if len(primary_timeline.lines) < 3:
            return False
        shifts = [
            secondary.start_ms - primary.start_ms
            for primary, secondary in zip(
                primary_timeline.lines,
                secondary_timeline.lines,
                strict=True,
            )
        ]
        return abs(median(shifts)) > ROBUST_DUAL_MAX_GLOBAL_SHIFT_MS

    def _safe_candidate(
        self,
        primary_line: AlignedLine,
        secondary_line: AlignedLine,
    ) -> bool:
        if secondary_line.confidence < self.min_confidence:
            return False
        if secondary_line.confidence < (
            primary_line.confidence + self.confidence_margin
        ):
            return False
        if (
            abs(secondary_line.start_ms - primary_line.start_ms)
            > self.max_line_shift_ms
            or abs(secondary_line.end_ms - primary_line.end_ms)
            > self.max_line_shift_ms
        ):
            return False
        if len(primary_line.tokens) != len(secondary_line.tokens):
            return False
        for primary_token, secondary_token in zip(
            primary_line.tokens,
            secondary_line.tokens,
            strict=True,
        ):
            if len(primary_token.moras) != len(secondary_token.moras):
                return False
            for mora in secondary_token.moras:
                if (
                    mora.end_ms <= mora.start_ms
                    or mora.end_ms - mora.start_ms
                    > ROBUST_DUAL_MAX_MORA_DURATION_MS
                ):
                    return False
        return True
