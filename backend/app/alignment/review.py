from __future__ import annotations

from typing import Any

from app.alignment.japanese import normalize_reading, split_moras
from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)


class TimelineReviewError(ValueError):
    """Raised when browser-reviewed timing cannot match the source timeline."""


def lyric_timeline_from_dict(value: dict[str, Any]) -> LyricTimeline:
    try:
        alignment_engine = value.get("alignment_engine") or "whisper_mora"
        alignment_model = value.get("alignment_model")
        lines = [
            AlignedLine(
                surface=str(line["surface"]),
                reading=str(line["reading"]),
                start_ms=int(line["start_ms"]),
                end_ms=int(line["end_ms"]),
                confidence=float(line["confidence"]),
                tokens=[
                    AlignedToken(
                        surface=str(token["surface"]),
                        reading=str(token["reading"]),
                        start_ms=int(token["start_ms"]),
                        end_ms=int(token["end_ms"]),
                        confidence=float(token["confidence"]),
                        moras=[
                            AlignedMora(
                                reading=str(mora["reading"]),
                                start_ms=int(mora["start_ms"]),
                                end_ms=int(mora["end_ms"]),
                                matched=bool(mora["matched"]),
                                confidence=float(mora["confidence"]),
                            )
                            for mora in token.get("moras", [])
                        ],
                    )
                    for token in line.get("tokens", [])
                ],
            )
            for line in value.get("lines", [])
        ]
        return LyricTimeline(
            confidence=float(value["confidence"]),
            lines=lines,
            warnings=[str(warning) for warning in value.get("warnings", [])],
            alignment_engine=str(alignment_engine),
            alignment_model=(
                str(alignment_model) if alignment_model is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TimelineReviewError("stored timeline is invalid") from exc


def _review_moras(reading: str, start_ms: int, end_ms: int) -> list[AlignedMora]:
    readings = split_moras(normalize_reading(reading))
    if not readings:
        return []
    duration = end_ms - start_ms
    return [
        AlignedMora(
            reading=mora,
            start_ms=start_ms + duration * index // len(readings),
            end_ms=start_ms + duration * (index + 1) // len(readings),
            matched=True,
            confidence=1.0,
        )
        for index, mora in enumerate(readings)
    ]


def apply_timeline_review(
    source: LyricTimeline,
    review: dict[str, Any],
) -> LyricTimeline:
    review_lines = review.get("lines")
    if not isinstance(review_lines, list) or len(review_lines) != len(source.lines):
        raise TimelineReviewError("review line count does not match source timeline")

    lines: list[AlignedLine] = []
    previous_end = 0
    for line_index, (source_line, reviewed_line) in enumerate(
        zip(source.lines, review_lines, strict=True)
    ):
        if not isinstance(reviewed_line, dict):
            raise TimelineReviewError(f"line {line_index + 1} is invalid")
        try:
            start_ms = int(reviewed_line["start_ms"])
            end_ms = int(reviewed_line["end_ms"])
            reviewed_tokens = reviewed_line["tokens"]
        except (KeyError, TypeError, ValueError) as exc:
            raise TimelineReviewError(f"line {line_index + 1} is invalid") from exc
        if start_ms < 0 or end_ms <= start_ms:
            raise TimelineReviewError(f"line {line_index + 1} has an invalid time range")
        if line_index and start_ms < previous_end:
            raise TimelineReviewError("reviewed lyric lines overlap")
        if not isinstance(reviewed_tokens, list) or len(reviewed_tokens) != len(
            source_line.tokens
        ):
            raise TimelineReviewError(
                f"line {line_index + 1} token count does not match source timeline"
            )

        tokens: list[AlignedToken] = []
        token_end = start_ms
        for token_index, (source_token, reviewed_token) in enumerate(
            zip(source_line.tokens, reviewed_tokens, strict=True)
        ):
            try:
                reading = str(reviewed_token["reading"]).strip()
                token_start = int(reviewed_token["start_ms"])
                token_finish = int(reviewed_token["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TimelineReviewError(
                    f"line {line_index + 1} token {token_index + 1} is invalid"
                ) from exc
            if (
                token_start < start_ms
                or token_finish > end_ms
                or token_finish < token_start
                or (
                    token_finish == token_start
                    and source_token.end_ms > source_token.start_ms
                )
                or token_start < token_end
            ):
                raise TimelineReviewError(
                    f"line {line_index + 1} token timing is invalid"
                )
            tokens.append(
                AlignedToken(
                    surface=source_token.surface,
                    reading=reading,
                    start_ms=token_start,
                    end_ms=token_finish,
                    confidence=1.0,
                    moras=_review_moras(reading, token_start, token_finish),
                )
            )
            token_end = token_finish

        lines.append(
            AlignedLine(
                surface=source_line.surface,
                reading="".join(token.reading for token in tokens),
                start_ms=start_ms,
                end_ms=end_ms,
                confidence=1.0,
                tokens=tokens,
            )
        )
        previous_end = end_ms

    return LyricTimeline(
        confidence=1.0,
        lines=lines,
        warnings=[*source.warnings, "browser_reviewed"],
        alignment_engine=source.alignment_engine,
        alignment_model=source.alignment_model,
    )
