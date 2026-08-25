from __future__ import annotations

import json
from dataclasses import replace
import re
import time
from typing import Any

import alkana
from janome.tokenizer import Tokenizer
from pykakasi import kakasi

from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.lyrics.numeric_reading import resolve_numeric_span
from app.core.event_logging import exception_details


DEEPSEEK_REVIEW_PROMPT = """
你是日语歌词读音审阅器。只输出 JSON，不要输出 Markdown。
输入已经由本地日语处理器生成，包含不可修改的 surface 和 token 索引。
只报告必须依赖日语上下文修正的最小连续 token 范围，不要重新生成全文或 token。
不得修改歌词表面文字，不得修正含英文或数字的范围，也不得声称根据未提供的音频判断实际唱法。
没有需要修正的内容时输出 {"corrections":[]}。
输出格式：
{"corrections":[{"line_index":0,"start_token":0,"end_token":1,
"surface":"...","current_reading":"...","corrected_reading":"..."}]}
end_token 使用 exclusive 下标。
""".strip()

_FA_KARA_ROMAJI = re.compile(r"[A-Za-z']+")
_LATIN_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
_HIRAGANA_READING = re.compile(r"[ぁ-ゖゝゞー・ 　]+")
_HIRAGANA_CHARACTER = re.compile(r"[ぁ-ゖゝゞ]")
_KANJI_SEGMENT_READING = re.compile(r"[ぁ-ゖゝゞー・]+")
_SMALL_KANA = frozenset("ゃゅょぁぃぅぇぉゎゕゖっー")
_READING_CONVERTER = kakasi()
_FOREIGN_READING_PARTS = re.compile(r"[A-Za-z]+|[0-9]+|[^A-Za-z0-9]+")
_FOREIGN_SEPARATORS = frozenset("-'’_")
_DIGIT_READINGS = {
    "0": "ぜろ",
    "1": "いち",
    "2": "に",
    "3": "さん",
    "4": "よん",
    "5": "ご",
    "6": "ろく",
    "7": "なな",
    "8": "はち",
    "9": "きゅう",
}
_LETTER_READINGS = {
    "a": "えー",
    "b": "びー",
    "c": "しー",
    "d": "でぃー",
    "e": "いー",
    "f": "えふ",
    "g": "じー",
    "h": "えいち",
    "i": "あい",
    "j": "じぇー",
    "k": "けー",
    "l": "える",
    "m": "えむ",
    "n": "えぬ",
    "o": "おー",
    "p": "ぴー",
    "q": "きゅー",
    "r": "あーる",
    "s": "えす",
    "t": "てぃー",
    "u": "ゆー",
    "v": "ぶい",
    "w": "だぶりゅー",
    "x": "えっくす",
    "y": "わい",
    "z": "ぜっと",
}


def _is_kanji(character: str) -> bool:
    return (
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
    )


def _reading_units(reading: str) -> list[str]:
    units: list[str] = []
    for character in reading:
        if character in _SMALL_KANA and units:
            units[-1] += character
        else:
            units.append(character)
    return units


def _surface_groups(surface: str) -> list[str]:
    groups: list[str] = []
    for character in surface:
        if _is_kanji(character):
            groups.append(character)
        elif groups and not _is_kanji(groups[-1]):
            groups[-1] += character
        else:
            groups.append(character)
    return groups


def _surface_segments(surface: str) -> list[tuple[bool, str]]:
    segments: list[tuple[bool, str]] = []
    for character in surface:
        is_kanji = _is_kanji(character)
        if segments and segments[-1][0] == is_kanji:
            segments[-1] = (is_kanji, segments[-1][1] + character)
        else:
            segments.append((is_kanji, character))
    return segments


def _reading_for_literal_surface(surface: str) -> str:
    return "".join(
        item["hira"] for item in _READING_CONVERTER.convert(surface)
    )


def _distribute_reading(reading: str, count: int) -> list[str]:
    units = _reading_units(reading)
    if count <= 1:
        return [reading]
    if len(units) < count:
        characters = list(reading)
        if len(characters) < count:
            return [reading, *[""] * (count - 1)]
        units = characters
    base, remainder = divmod(len(units), count)
    result: list[str] = []
    offset = 0
    for index in range(count):
        size = base + (1 if index < remainder else 0)
        result.append("".join(units[offset : offset + size]))
        offset += size
    return result


def _distribute_kanji_reading(
    characters: list[str],
    reading: str,
) -> list[str]:
    result: list[str | None] = [None] * len(characters)
    remaining = reading
    left = 0
    right = len(characters) - 1

    while left <= right:
        candidate = _reading_for_literal_surface(characters[left])
        tail = remaining[len(candidate) :] if candidate else remaining
        if not candidate or not remaining.startswith(candidate):
            break
        if len(_reading_units(tail)) < right - left:
            break
        result[left] = candidate
        remaining = tail
        left += 1

    while right >= left:
        candidate = _reading_for_literal_surface(characters[right])
        head = remaining[: -len(candidate)] if candidate else remaining
        if not candidate or not remaining.endswith(candidate):
            break
        if len(_reading_units(head)) < right - left:
            break
        result[right] = candidate
        remaining = head
        right -= 1

    fallback = iter(_distribute_reading(remaining, right - left + 1))
    for index in range(left, right + 1):
        result[index] = next(fallback)
    return [item or "" for item in result]


def split_token_by_kanji(token: LyricToken) -> list[LyricToken]:
    kanji_count = sum(_is_kanji(character) for character in token.surface)
    groups = _surface_groups(token.surface)
    if (
        kanji_count == 0
        or len(groups) == 1
        or token.alignment_pronunciation is not None
    ):
        return [token]

    segments = _surface_segments(token.surface)
    pattern_parts = ["^"]
    for is_kanji, segment in segments:
        pattern_parts.append(
            "(.*?)"
            if is_kanji
            else re.escape(_reading_for_literal_surface(segment))
        )
    pattern_parts.append("$")
    match = re.fullmatch("".join(pattern_parts), token.reading)
    if match is not None and all(match.groups()):
        captured_readings = iter(match.groups())
        refined: list[LyricToken] = []
        for is_kanji, segment in segments:
            if is_kanji:
                readings = _distribute_kanji_reading(
                    list(segment),
                    next(captured_readings),
                )
                refined.extend(
                    LyricToken(surface=character, reading=reading)
                    for character, reading in zip(
                        segment,
                        readings,
                        strict=True,
                    )
                )
            else:
                refined.append(
                    LyricToken(
                        surface=segment,
                        reading=_reading_for_literal_surface(segment),
                    )
                )
        return refined

    fallback_readings = _distribute_reading(token.reading, len(groups))
    return [
        LyricToken(
            surface=group,
            reading=reading,
        )
        for group, reading in zip(
            groups,
            fallback_readings,
            strict=True,
        )
    ]


def split_tokens_by_kanji(tokens: list[LyricToken]) -> list[LyricToken]:
    return [
        refined
        for token in tokens
        for refined in split_token_by_kanji(token)
    ]


def contains_fa_kara_annotations(text: str) -> bool:
    return any(marker in text for marker in ("{", "}", "[", "]"))


def normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class LyricProcessingError(ValueError):
    """Raised when an AI lyric response cannot be safely consumed."""


class DeepSeekReadingReviewer:
    def __init__(self, *, client: Any) -> None:
        self.client = client

    def review(self, document: LyricDocument) -> LyricDocument:
        request_payload = {
            "lines": [
                {
                    "line_index": line_index,
                    "surface": line.surface,
                    "tokens": [
                        {
                            "token_index": token_index,
                            "surface": token.surface,
                            "reading": token.reading,
                        }
                        for token_index, token in enumerate(line.tokens)
                    ],
                }
                for line_index, line in enumerate(document.lines)
            ]
        }
        response = self.client.complete_json(
            system_prompt=DEEPSEEK_REVIEW_PROMPT,
            user_prompt=json.dumps(request_payload, ensure_ascii=False),
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("corrections"), list
        ):
            raise LyricProcessingError("review response must contain corrections list")

        validated: list[dict[str, Any]] = []
        for raw_correction in response["corrections"]:
            if not isinstance(raw_correction, dict):
                raise LyricProcessingError("correction must be an object")
            try:
                line_index = raw_correction["line_index"]
                start = raw_correction["start_token"]
                end = raw_correction["end_token"]
                surface = str(raw_correction["surface"])
                current_reading = str(raw_correction["current_reading"])
                corrected_reading = str(raw_correction["corrected_reading"])
            except KeyError as exc:
                raise LyricProcessingError("correction fields are invalid") from exc
            if any(type(value) is not int for value in (line_index, start, end)):
                raise LyricProcessingError(
                    "correction indices must be JSON integers"
                )

            if not 0 <= line_index < len(document.lines):
                raise LyricProcessingError("correction line is out of bounds")
            line = document.lines[line_index]
            if not 0 <= start < end <= len(line.tokens):
                raise LyricProcessingError("correction token range is invalid")
            selected = line.tokens[start:end]
            rebuilt_surface = "".join(token.surface for token in selected)
            rebuilt_reading = "".join(token.reading for token in selected)
            if rebuilt_surface != surface:
                raise LyricProcessingError("correction surface does not match tokens")
            if rebuilt_reading != current_reading:
                raise LyricProcessingError(
                    "correction current reading does not match tokens"
                )
            if corrected_reading == current_reading:
                raise LyricProcessingError("correction is a no-op")
            if _LATIN_OR_DIGIT.search(rebuilt_surface):
                raise LyricProcessingError(
                    "correction range contains Latin or digits"
                )
            if any(
                token.alignment_pronunciation is not None for token in selected
            ):
                raise LyricProcessingError(
                    "correction range contains alignment pronunciation"
                )
            if (
                _HIRAGANA_CHARACTER.search(corrected_reading) is None
                or _HIRAGANA_READING.fullmatch(corrected_reading) is None
            ):
                raise LyricProcessingError(
                    "corrected reading must be non-empty hiragana"
                )

            pattern_parts = ["^"]
            for is_kanji, segment in _surface_segments(rebuilt_surface):
                pattern_parts.append(
                    "(.+?)"
                    if is_kanji
                    else re.escape(_reading_for_literal_surface(segment))
                )
            pattern_parts.append("$")
            anchor_match = re.fullmatch(
                "".join(pattern_parts),
                corrected_reading,
            )
            if anchor_match is None:
                raise LyricProcessingError(
                    "correction does not preserve literal kana"
                )
            if any(
                _KANJI_SEGMENT_READING.fullmatch(reading) is None
                for reading in anchor_match.groups()
            ):
                raise LyricProcessingError(
                    "correction kanji reading contains invalid whitespace"
                )
            replacement = split_token_by_kanji(
                LyricToken(
                    surface=rebuilt_surface,
                    reading=corrected_reading,
                )
            )
            if (
                any(not token.reading.strip() for token in replacement)
                or "".join(token.surface for token in replacement)
                != rebuilt_surface
                or "".join(token.reading for token in replacement)
                != corrected_reading
            ):
                raise LyricProcessingError(
                    "correction would create an empty token reading"
                )
            validated.append(
                {
                    "line_index": line_index,
                    "start_token": start,
                    "end_token": end,
                    "surface": surface,
                    "corrected_reading": corrected_reading,
                    "replacement": replacement,
                }
            )

        corrections_by_line: dict[int, list[dict[str, Any]]] = {}
        for correction in validated:
            corrections_by_line.setdefault(correction["line_index"], []).append(
                correction
            )
        for corrections in corrections_by_line.values():
            ordered = sorted(corrections, key=lambda item: item["start_token"])
            if any(
                left["end_token"] > right["start_token"]
                for left, right in zip(ordered, ordered[1:])
            ):
                raise LyricProcessingError("correction ranges overlap")

        reviewed_lines: list[LyricLine] = []
        for line_index, line in enumerate(document.lines):
            tokens = list(line.tokens)
            corrections = corrections_by_line.get(line_index, [])
            for correction in sorted(
                corrections,
                key=lambda item: item["start_token"],
                reverse=True,
            ):
                start = correction["start_token"]
                end = correction["end_token"]
                tokens[start:end] = correction["replacement"]
            reviewed_lines.append(
                replace(
                    line,
                    reading="".join(token.reading for token in tokens),
                    tokens=tokens,
                )
            )
        return replace(
            document,
            provider="local+deepseek",
            lines=reviewed_lines,
        )


class LocalJapaneseLyricProcessor:
    def __init__(self) -> None:
        self.converter = kakasi()
        self.tokenizer = Tokenizer()

    def _hiragana(self, text: str) -> str:
        return "".join(item["hira"] for item in self.converter.convert(text))

    def _foreign_reading(self, surface: str) -> str:
        reading_parts: list[str] = []
        for part in _FOREIGN_READING_PARTS.findall(surface):
            if part.isascii() and part.isalpha():
                katakana = alkana.get_kana(part)
                reading_parts.append(
                    self._hiragana(katakana)
                    if katakana is not None
                    else "".join(_LETTER_READINGS[letter] for letter in part.lower())
                )
            elif part.isascii() and part.isdigit():
                reading_parts.append(
                    "".join(_DIGIT_READINGS[digit] for digit in part)
                )
            elif all(character in _FOREIGN_SEPARATORS for character in part):
                continue
            else:
                reading_parts.append(self._hiragana(part))
        return "".join(reading_parts)

    def _surface_reading(self, surface: str) -> str:
        if _LATIN_OR_DIGIT.search(surface):
            return self._foreign_reading(surface)
        return self._hiragana(surface)

    def _plain_tokens(self, text: str) -> list[LyricToken]:
        tokens: list[LyricToken] = []
        items = list(self.tokenizer.tokenize(text))
        surfaces = [item.surface for item in items]
        index = 0
        while index < len(items):
            item = items[index]
            surface = item.surface
            numeric = resolve_numeric_span(surfaces, index)
            if numeric is not None:
                tokens.extend(
                    LyricToken(surface=part.surface, reading=part.reading)
                    for part in numeric.parts
                )
                index += numeric.consumed_items
                continue
            alignment_pronunciation = None
            major_part = item.part_of_speech.split(",", maxsplit=1)[0]
            if _LATIN_OR_DIGIT.search(surface) or item.reading == "*":
                reading = self._surface_reading(surface)
            else:
                reading = self._hiragana(item.reading)
            if major_part == "助詞" and surface == "は":
                alignment_pronunciation = "wa"
            elif major_part == "助詞" and surface == "へ":
                alignment_pronunciation = "e"
            tokens.append(
                LyricToken(
                    surface=surface,
                    reading=reading,
                    alignment_pronunciation=alignment_pronunciation,
                )
            )
            index += 1
        return split_tokens_by_kanji(tokens)

    def _annotated_tokens(self, source: str) -> list[LyricToken]:
        tokens: list[LyricToken] = []
        plain_start = 0
        index = 0
        while index < len(source):
            opener = source[index]
            if opener not in "{[":
                if opener in "}]":
                    raise LyricProcessingError(
                        f"FA-Kara annotation has an unmatched {opener!r}"
                    )
                index += 1
                continue

            if plain_start < index:
                tokens.extend(self._plain_tokens(source[plain_start:index]))
            closer = "}" if opener == "{" else "]"
            end = source.find(closer, index + 1)
            if end < 0:
                raise LyricProcessingError(
                    f"FA-Kara annotation starting with {opener!r} is not closed"
                )
            content = source[index + 1 : end]
            if content.count("|") != 1:
                raise LyricProcessingError(
                    "FA-Kara annotation must contain exactly one | separator"
                )
            surface, pronunciation = content.split("|", maxsplit=1)
            if not surface or not pronunciation:
                raise LyricProcessingError(
                    "FA-Kara annotation surface and pronunciation cannot be empty"
                )
            if opener == "{":
                tokens.extend(
                    split_token_by_kanji(
                        LyricToken(
                            surface=surface,
                            reading=self._hiragana(pronunciation),
                        )
                    )
                )
            else:
                if _FA_KARA_ROMAJI.fullmatch(pronunciation) is None:
                    raise LyricProcessingError(
                        "FA-Kara hidden pronunciation must use Latin letters"
                    )
                tokens.append(
                    LyricToken(
                        surface=surface,
                        reading=self._hiragana(surface),
                        alignment_pronunciation=pronunciation.lower(),
                    )
                )
            index = end + 1
            plain_start = index

        if plain_start < len(source):
            tokens.extend(self._plain_tokens(source[plain_start:]))
        return tokens

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        lines: list[LyricLine] = []
        for source in source_lines:
            tokens = self._annotated_tokens(source)
            surface = "".join(token.surface for token in tokens)
            lines.append(
                LyricLine(
                    source=source,
                    surface=surface,
                    reading="".join(token.reading for token in tokens),
                    tokens=tokens,
                )
            )
        return LyricDocument(
            provider="local",
            source_text="\n".join(source_lines),
            lines=lines,
            warnings=["local_reading_may_be_inaccurate"],
        )


def normalize_unconverted_foreign_readings(
    document: LyricDocument,
) -> LyricDocument:
    processor = LocalJapaneseLyricProcessor()
    changed = False
    normalized_lines: list[LyricLine] = []
    for line in document.lines:
        normalized_tokens: list[LyricToken] = []
        for token in line.tokens:
            should_generate = (
                token.alignment_pronunciation is None
                and _LATIN_OR_DIGIT.search(token.surface) is not None
                and (
                    not token.reading.strip()
                    or _LATIN_OR_DIGIT.search(token.reading) is not None
                )
            )
            if should_generate:
                normalized_tokens.append(
                    replace(
                        token,
                        reading=processor._surface_reading(token.surface),
                    )
                )
                changed = True
            else:
                normalized_tokens.append(token)
        normalized_lines.append(
            replace(
                line,
                reading="".join(token.reading for token in normalized_tokens),
                tokens=normalized_tokens,
            )
        )
    if not changed:
        return document
    return replace(document, lines=normalized_lines)


class ReviewedLyricProcessor:
    def __init__(
        self,
        *,
        base: Any,
        reviewer: Any,
        event_logger: Any | None = None,
    ) -> None:
        self.base = base
        self.reviewer = reviewer
        self.event_logger = event_logger

    def process(self, text: str) -> LyricDocument:
        document = self.base.process(text)
        if contains_fa_kara_annotations(text):
            return document

        source_lines = normalized_lines(text)
        client = getattr(self.reviewer, "client", None)
        call_details = {
            "attempt": 1,
            "character_count": sum(len(line) for line in source_lines),
            "line_count": len(source_lines),
            "model": getattr(client, "model", None),
            "timeout_seconds": getattr(client, "timeout_seconds", None),
        }
        started = time.perf_counter()
        if self.event_logger is not None:
            self.event_logger.emit(
                event="external.started",
                level="INFO",
                category="external",
                message="DeepSeek 开始本地读音审阅",
                component="deepseek",
                details=call_details,
            )
        try:
            reviewed = self.reviewer.review(document)
        except Exception as exc:
            if self.event_logger is not None:
                self.event_logger.emit(
                    event="external.failed",
                    level="WARNING",
                    category="external",
                    message="DeepSeek 审阅失败，保留本地结果",
                    component="deepseek",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    details={
                        "attempt": 1,
                        "retry_count": 0,
                        "fallback_component": type(self.base).__name__,
                        **exception_details(exc),
                    },
                )
                self.event_logger.emit(
                    event="stage.fallback",
                    level="WARNING",
                    category="pipeline",
                    message="DeepSeek 审阅失败，保留本地结果",
                    component="deepseek",
                    details={
                        "reason": "deepseek_review_failed",
                        "fallback_component": type(self.base).__name__,
                    },
                )
            return replace(
                document,
                warnings=[
                    *document.warnings,
                    f"deepseek_review_failed:{type(exc).__name__}",
                ],
            )
        if self.event_logger is not None:
            self.event_logger.emit(
                event="external.completed",
                level="INFO",
                category="external",
                message="DeepSeek 完成本地读音审阅",
                component="deepseek",
                duration_ms=(time.perf_counter() - started) * 1000,
                details={
                    "attempt": 1,
                    "provider": reviewed.provider,
                    "result_line_count": len(reviewed.lines),
                    "warning_count": len(reviewed.warnings),
                },
            )
        return reviewed
