from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LyricToken:
    surface: str
    reading: str
    alignment_pronunciation: str | None = None


@dataclass(frozen=True)
class LyricLine:
    source: str
    surface: str
    reading: str
    tokens: list[LyricToken] = field(default_factory=list)


@dataclass(frozen=True)
class LyricDocument:
    provider: str
    source_text: str
    lines: list[LyricLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lyric_document_from_dict(value: dict[str, Any]) -> LyricDocument:
    return LyricDocument(
        provider=str(value["provider"]),
        source_text=str(value["source_text"]),
        lines=[
            LyricLine(
                source=str(line["source"]),
                surface=str(line["surface"]),
                reading=str(line["reading"]),
                tokens=[
                    LyricToken(
                        surface=str(token["surface"]),
                        reading=str(token["reading"]),
                        alignment_pronunciation=(
                            str(token["alignment_pronunciation"])
                            if token.get("alignment_pronunciation") is not None
                            else None
                        ),
                    )
                    for token in line.get("tokens", [])
                ],
            )
            for line in value.get("lines", [])
        ],
        warnings=[str(warning) for warning in value.get("warnings", [])],
    )

