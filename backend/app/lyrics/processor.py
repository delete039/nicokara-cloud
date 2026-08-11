from __future__ import annotations

import json
from dataclasses import replace
import re
from typing import Any

from janome.tokenizer import Tokenizer
from pykakasi import kakasi

from app.lyrics.models import LyricDocument, LyricLine, LyricToken


SYSTEM_PROMPT = """
你是日语歌词格式化器。只输出 JSON，不要输出 Markdown。
保持输入行顺序，为每行生成：
- surface：修正明显表记错误后的歌词
- reading：整行平假名读音
- tokens：用于 Ruby 注音的 surface/reading 数组
tokens 的 surface 拼接必须严格等于该行 surface。
输出格式：{"lines":[{"surface":"...","reading":"...","tokens":[...]}]}
""".strip()

_FA_KARA_ROMAJI = re.compile(r"[A-Za-z']+")


def contains_fa_kara_annotations(text: str) -> bool:
    return any(marker in text for marker in ("{", "}", "[", "]"))


def normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


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
        response = self.client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps({"lines": source_lines}, ensure_ascii=False),
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
                    reading=self._hiragana(surface),
                    alignment_pronunciation=alignment_pronunciation,
                )
            )
        return tokens

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
                tokens.append(
                    LyricToken(
                        surface=surface,
                        reading=self._hiragana(pronunciation),
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


class ResilientLyricProcessor:
    def __init__(self, *, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def process(self, text: str) -> LyricDocument:
        try:
            return self.primary.process(text)
        except Exception as exc:
            document = self.fallback.process(text)
            return replace(
                document,
                warnings=[
                    *document.warnings,
                    f"deepseek_fallback:{type(exc).__name__}",
                ],
            )
