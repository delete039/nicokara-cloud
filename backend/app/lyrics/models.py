from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LyricToken:
    surface: str
    reading: str


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

