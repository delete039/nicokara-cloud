from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class AlignedMora:
    reading: str
    start_ms: int
    end_ms: int
    matched: bool
    confidence: float


@dataclass(frozen=True)
class AlignedToken:
    surface: str
    reading: str
    start_ms: int
    end_ms: int
    confidence: float
    moras: list[AlignedMora] = field(default_factory=list)


@dataclass(frozen=True)
class AlignedLine:
    surface: str
    reading: str
    start_ms: int
    end_ms: int
    confidence: float
    tokens: list[AlignedToken] = field(default_factory=list)


@dataclass(frozen=True)
class LyricTimeline:
    confidence: float
    lines: list[AlignedLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    alignment_engine: str = "whisper_mora"
    alignment_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def shift_timeline(timeline: LyricTimeline, offset_ms: int) -> LyricTimeline:
    """Shift every timeline boundary while keeping all segments valid."""
    if offset_ms == 0 or not timeline.lines:
        return timeline

    def shifted(value: int) -> int:
        return max(0, value + offset_ms)

    def shifted_range(start_ms: int, end_ms: int) -> tuple[int, int]:
        start = shifted(start_ms)
        end = max(start, shifted(end_ms))
        return start, end

    lines: list[AlignedLine] = []
    for line in timeline.lines:
        line_start, line_end = shifted_range(line.start_ms, line.end_ms)
        tokens: list[AlignedToken] = []
        for token in line.tokens:
            token_start, token_end = shifted_range(token.start_ms, token.end_ms)
            moras: list[AlignedMora] = []
            for mora in token.moras:
                mora_start, mora_end = shifted_range(
                    mora.start_ms,
                    mora.end_ms,
                )
                moras.append(
                    replace(
                        mora,
                        start_ms=mora_start,
                        end_ms=mora_end,
                    )
                )
            tokens.append(
                replace(
                    token,
                    start_ms=token_start,
                    end_ms=token_end,
                    moras=moras,
                )
            )
        lines.append(
            replace(
                line,
                start_ms=line_start,
                end_ms=line_end,
                tokens=tokens,
            )
        )

    return replace(
        timeline,
        lines=lines,
        warnings=[
            *timeline.warnings,
            f"timeline_offset_applied:{offset_ms}ms",
        ],
    )


def close_mora_gaps(timeline: LyricTimeline) -> LyricTimeline:
    """Extend each mora through positive gaps inside its own lyric line."""
    lines: list[AlignedLine] = []
    for line in timeline.lines:
        tokens = [
            replace(token, moras=list(token.moras))
            for token in line.tokens
        ]
        references = [
            (token_index, mora_index)
            for token_index, token in enumerate(tokens)
            for mora_index in range(len(token.moras))
        ]

        for current_ref, next_ref in zip(references, references[1:]):
            current_token_index, current_mora_index = current_ref
            next_token_index, next_mora_index = next_ref
            current_token = tokens[current_token_index]
            next_token = tokens[next_token_index]
            current_mora = current_token.moras[current_mora_index]
            next_mora = next_token.moras[next_mora_index]
            if current_mora.end_ms >= next_mora.start_ms:
                continue

            boundary = next_mora.start_ms
            current_moras = list(current_token.moras)
            current_moras[current_mora_index] = replace(
                current_mora,
                end_ms=boundary,
            )
            tokens[current_token_index] = replace(
                current_token,
                end_ms=(
                    boundary
                    if current_token_index != next_token_index
                    else current_token.end_ms
                ),
                moras=current_moras,
            )

            if current_token_index != next_token_index:
                for token_index in range(
                    current_token_index + 1,
                    next_token_index,
                ):
                    tokens[token_index] = replace(
                        tokens[token_index],
                        start_ms=boundary,
                        end_ms=boundary,
                    )
                tokens[next_token_index] = replace(
                    tokens[next_token_index],
                    start_ms=boundary,
                )

        lines.append(replace(line, tokens=tokens))

    return replace(timeline, lines=lines)
