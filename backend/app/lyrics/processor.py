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
from app.core.event_logging import exception_details


SYSTEM_PROMPT = """
你是日语歌词格式化器。只输出 JSON，不要输出 Markdown。
保持输入行顺序，为每行生成：
- surface：修正明显表记错误后的歌词
- reading：整行平假名读音
- tokens：用于 Ruby 注音的 surface/reading 数组；每个汉字必须单独作为一个 token，
  后续连续假名可以合并为一个 token，不得把多个汉字放在同一个 token 中
  例如「物語」拆成「物/もの」「語/がたり」，
  「知らない」拆成「知/し」「らない/らない」
- surface 中的英文或数字必须保留原表记；对应的整行 reading 和 token reading
  必须根据歌词中的实际唱法改写为平假名，不得保留英文字母或数字，
  例如「LOVE 39」可写为「LOVE/らぶ」「39/さんきゅー」
tokens 的 surface 拼接必须严格等于该行 surface。
输出格式：{"lines":[{"surface":"...","reading":"...","tokens":[...]}]}
""".strip()

_FA_KARA_ROMAJI = re.compile(r"[A-Za-z']+")
_LATIN_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
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


def has_unconverted_latin_or_digits(response: dict[str, Any]) -> bool:
    for line in response.get("lines", []):
        if (
            _LATIN_OR_DIGIT.search(str(line.get("surface", "")))
            and _LATIN_OR_DIGIT.search(str(line.get("reading", "")))
        ):
            return True
        for token in line.get("tokens", []):
            if (
                _LATIN_OR_DIGIT.search(str(token.get("surface", "")))
                and _LATIN_OR_DIGIT.search(str(token.get("reading", "")))
            ):
                return True
    return False


class LyricProcessingError(ValueError):
    """Raised when an AI lyric response cannot be safely consumed."""


class DeepSeekLyricProcessor:
    def __init__(self, *, client: Any) -> None:
        self.client = client

    def process(self, text: str) -> LyricDocument:
        if contains_fa_kara_annotations(text):
            return LocalJapaneseLyricProcessor().process(text)
        source_lines = normalized_lines(text)
        source_text = "\n".join(source_lines)
        request_payload: dict[str, Any] = {"lines": source_lines}
        response = self.client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(request_payload, ensure_ascii=False),
        )
        if has_unconverted_latin_or_digits(response):
            request_payload["纠正"] = (
                "上一次结果仍在 reading 中保留了英文或数字。请保持 surface "
                "不变，并按实际唱法把对应 reading 全部改为平假名。"
            )
            response = self.client.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(request_payload, ensure_ascii=False),
            )
            if has_unconverted_latin_or_digits(response):
                raise LyricProcessingError(
                    "automatic English or numeric kana reading was not generated"
                )
        lines: list[LyricLine] = []
        for source, result in zip(source_lines, response["lines"], strict=True):
            tokens = [
                LyricToken(
                    surface=token["surface"],
                    reading=token["reading"],
                )
                for token in result["tokens"]
            ]
            if "".join(token.surface for token in tokens) != result["surface"]:
                raise LyricProcessingError("tokens do not reconstruct surface")
            tokens = split_tokens_by_kanji(tokens)
            lines.append(
                LyricLine(
                    source=source,
                    surface=result["surface"],
                    reading=result["reading"],
                    tokens=tokens,
                )
            )
        return LyricDocument(
            provider="deepseek",
            source_text=source_text,
            lines=lines,
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
        for item in self.tokenizer.tokenize(text):
            surface = item.surface
            alignment_pronunciation = None
            major_part = item.part_of_speech.split(",", maxsplit=1)[0]
            if major_part == "助詞" and surface == "は":
                alignment_pronunciation = "wa"
            elif major_part == "助詞" and surface == "へ":
                alignment_pronunciation = "e"
            tokens.append(
                LyricToken(
                    surface=surface,
                    reading=self._surface_reading(surface),
                    alignment_pronunciation=alignment_pronunciation,
                )
            )
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


class ResilientLyricProcessor:
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

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        client = getattr(self.primary, "client", None)
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
                message="开始调用 DeepSeek 处理歌词注音",
                component="deepseek",
                details=call_details,
            )
        try:
            document = self.primary.process(text)
        except Exception as exc:
            if self.event_logger is not None:
                self.event_logger.emit(
                    event="external.failed",
                    level="WARNING",
                    category="external",
                    message="DeepSeek 歌词处理失败，将使用本地处理器",
                    component="deepseek",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    details={
                        "attempt": 1,
                        "retry_count": 0,
                        "fallback_component": type(self.fallback).__name__,
                        **exception_details(exc),
                    },
                )
                self.event_logger.emit(
                    event="stage.fallback",
                    level="WARNING",
                    category="pipeline",
                    message="歌词处理切换到本地注音处理器",
                    component="deepseek",
                    details={
                        "reason": "deepseek_unavailable",
                        "fallback_component": type(self.fallback).__name__,
                    },
                )
            document = self.fallback.process(text)
            return replace(
                document,
                warnings=[
                    *document.warnings,
                    f"deepseek_fallback:{type(exc).__name__}",
                ],
            )
        if self.event_logger is not None:
            self.event_logger.emit(
                event="external.completed",
                level="INFO",
                category="external",
                message="DeepSeek 歌词注音处理完成",
                component="deepseek",
                duration_ms=(time.perf_counter() - started) * 1000,
                details={
                    "attempt": 1,
                    "provider": document.provider,
                    "result_line_count": len(document.lines),
                    "warning_count": len(document.warnings),
                },
            )
        return document
