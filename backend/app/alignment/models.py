from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
