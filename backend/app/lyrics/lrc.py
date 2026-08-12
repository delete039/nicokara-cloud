from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.alignment.models import (
    AlignedLine,
    AlignedToken,
    LyricTimeline,
)


_TIMESTAMP = re.compile(r"\[(\d+):(\d+)(?:[.:](\d+))?\]")
_INLINE_RUBY = re.compile(r"\{([^|{}]+)\|[^{}]*\}")


@dataclass(frozen=True)
class ParsedLrc:
    lyrics_text: str
    line_starts_ms: list[int | None]

    @property
    def has_timing(self) -> bool:
        return any(value is not None for value in self.line_starts_ms)


def _timestamp_ms(match: re.Match[str]) -> int:
    fraction = match.group(3) or "0"
    fraction_ms = round(int(fraction) * 1000 / (10 ** len(fraction)))
    return (int(match.group(1)) * 60 + int(match.group(2))) * 1000 + fraction_ms


def parse_lrc(text: str) -> ParsedLrc:
    lyrics: list[str] = []
    starts: list[int | None] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.lower().startswith("@ruby"):
            continue
        matches = list(_TIMESTAMP.finditer(line))
        lyric = _TIMESTAMP.sub("", line)
        lyric = _INLINE_RUBY.sub(lambda match: match.group(1), lyric).strip()
        if not lyric:
            continue
        if line.startswith("[") and not matches:
            continue
        lyrics.append(lyric)
        starts.append(_timestamp_ms(matches[0]) if matches else None)
    return ParsedLrc("\n".join(lyrics), starts)


def _map_time(value: int, old_start: int, old_end: int, new_start: int, new_end: int) -> int:
    if old_end <= old_start:
        return new_start
    progress = (value - old_start) / (old_end - old_start)
    return round(new_start + max(0.0, min(1.0, progress)) * (new_end - new_start))


def _retime_token(
    token: AlignedToken,
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> AlignedToken:
    return replace(
        token,
        start_ms=_map_time(token.start_ms, old_start, old_end, new_start, new_end),
        end_ms=_map_time(token.end_ms, old_start, old_end, new_start, new_end),
        moras=[
            replace(
                mora,
                start_ms=_map_time(mora.start_ms, old_start, old_end, new_start, new_end),
                end_ms=_map_time(mora.end_ms, old_start, old_end, new_start, new_end),
            )
            for mora in token.moras
        ],
    )


def retime_timeline_from_lrc(
    timeline: LyricTimeline,
    line_starts_ms: list[int | None],
) -> LyricTimeline:
    if len(line_starts_ms) != len(timeline.lines) or not any(
        value is not None for value in line_starts_ms
    ):
        return timeline

    lines: list[AlignedLine] = []
    for index, line in enumerate(timeline.lines):
        new_start = line_starts_ms[index]
        if new_start is None:
            new_start = max(lines[-1].end_ms if lines else 0, line.start_ms)
        next_start = (
            line_starts_ms[index + 1]
            if index + 1 < len(line_starts_ms)
            else None
        )
        duration = max(1, line.end_ms - line.start_ms)
        new_end = new_start + duration
        if next_start is not None and next_start > new_start:
            new_end = min(new_end, next_start)
        lines.append(
            replace(
                line,
                start_ms=new_start,
                end_ms=new_end,
                tokens=[
                    _retime_token(
                        token,
                        line.start_ms,
                        line.end_ms,
                        new_start,
                        new_end,
                    )
                    for token in line.tokens
                ],
            )
        )
    return replace(
        timeline,
        lines=lines,
        warnings=[*timeline.warnings, "lrc_timing_applied"],
    )
