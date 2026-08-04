from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

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


def normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class LyricProcessingError(ValueError):
    """Raised when an AI lyric response cannot be safely consumed."""


class DeepSeekLyricProcessor:
    def __init__(self, *, client: Any) -> None:
        self.client = client

    def process(self, text: str) -> LyricDocument:
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

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        lines: list[LyricLine] = []
        for source in source_lines:
            converted = self.converter.convert(source)
            tokens = [
                LyricToken(surface=item["orig"], reading=item["hira"])
                for item in converted
            ]
            lines.append(
                LyricLine(
                    source=source,
                    surface=source,
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
