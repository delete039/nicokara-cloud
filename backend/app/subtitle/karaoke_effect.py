from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from app.alignment.models import AlignedLine, AlignedToken


@dataclass(frozen=True)
class KaraokeChunk:
    text: str
    duration_cs: int


def escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def is_sung_text(text: str) -> bool:
    return any(
        not unicodedata.category(character).startswith(("P", "S", "Z"))
        for character in text
    )


def character_chunks(token: AlignedToken) -> list[KaraokeChunk]:
    characters = list(token.surface)
    if not characters:
        return []
    sung_indices = [
        index
        for index, character in enumerate(characters)
        if is_sung_text(character)
    ]
    if not sung_indices:
        return [
            KaraokeChunk(text=character, duration_cs=0)
            for character in characters
        ]
    total_cs = round((token.end_ms - token.start_ms) / 10)
    durations = [0] * len(characters)
    if token.moras and len(token.moras) == len(sung_indices):
        mora_durations = [
            max(0, round((mora.end_ms - mora.start_ms) / 10))
            for mora in token.moras
        ]
        difference = max(0, total_cs) - sum(mora_durations)
        mora_durations[-1] = max(0, mora_durations[-1] + difference)
        for character_index, duration in zip(
            sung_indices,
            mora_durations,
            strict=True,
        ):
            durations[character_index] = duration
    else:
        base, remainder = divmod(max(0, total_cs), len(sung_indices))
        for position, character_index in enumerate(sung_indices):
            durations[character_index] = base + (
                1 if position >= len(sung_indices) - remainder else 0
            )
    return [
        KaraokeChunk(
            text=character,
            duration_cs=durations[index],
        )
        for index, character in enumerate(characters)
    ]


def line_chunks(line: AlignedLine) -> list[KaraokeChunk]:
    result: list[KaraokeChunk] = []
    for index, token in enumerate(line.tokens):
        chunks = character_chunks(token)
        if not chunks:
            continue
        next_start_ms = (
            line.tokens[index + 1].start_ms
            if index + 1 < len(line.tokens)
            else line.end_ms
        )
        gap_cs = round(max(0, next_start_ms - token.end_ms) / 10)
        if not result:
            gap_cs += round(max(0, token.start_ms - line.start_ms) / 10)
        sung_index = next(
            (
                chunk_index
                for chunk_index in range(len(chunks) - 1, -1, -1)
                if is_sung_text(chunks[chunk_index].text)
            ),
            None,
        )
        if sung_index is not None:
            chunks[sung_index] = KaraokeChunk(
                text=chunks[sung_index].text,
                duration_cs=chunks[sung_index].duration_cs + gap_cs,
            )
        result.extend(chunks)

    if result:
        target_cs = round((line.end_ms - line.start_ms) / 10)
        difference = target_cs - sum(chunk.duration_cs for chunk in result)
        if difference > 0:
            index = next(
                index
                for index in range(len(result) - 1, -1, -1)
                if is_sung_text(result[index].text)
            )
            result[index] = KaraokeChunk(
                text=result[index].text,
                duration_cs=result[index].duration_cs + difference,
            )
        elif difference < 0:
            remaining = -difference
            for index in range(len(result) - 1, -1, -1):
                if not is_sung_text(result[index].text):
                    continue
                reduction = min(result[index].duration_cs, remaining)
                result[index] = KaraokeChunk(
                    text=result[index].text,
                    duration_cs=result[index].duration_cs - reduction,
                )
                remaining -= reduction
                if remaining == 0:
                    break
    return result


def render_karaoke(chunks: list[KaraokeChunk]) -> str:
    return "".join(
        (
            rf"{{\kf{chunk.duration_cs}}}{escape_ass_text(chunk.text)}"
            if chunk.duration_cs > 0 and is_sung_text(chunk.text)
            else escape_ass_text(chunk.text)
        )
        for chunk in chunks
    )
