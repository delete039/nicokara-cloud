from __future__ import annotations

import re
import json
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pykakasi import kakasi

from app.ai.whisper import TranscriptDocument
from app.alignment.japanese import normalize_reading, split_moras
from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
    close_mora_gaps,
)
from app.lyrics.models import LyricDocument


MMS_MODEL_NAME = "torchaudio.pipelines.MMS_FA"
DEFAULT_MIN_CONFIDENCE = 0.15
DEFAULT_MAX_MORA_DURATION_MS = 15_000
_ROMAJI_FILTER = re.compile("[^a-z']")
_LATIN_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
_CONVERTER = kakasi()


class ForcedAlignmentError(RuntimeError):
    """Raised when MMS_FA cannot produce a complete, usable alignment."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        timeout_seconds: float | None = None,
        stderr_tail: str | None = None,
        command: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.timeout_seconds = timeout_seconds
        self.stderr_tail = stderr_tail
        self.command = command


@dataclass(frozen=True)
class MMSMoraSpan:
    start_ms: int
    end_ms: int
    score: float


class SubprocessMMSRuntime:
    """Run the memory-heavy MMS model in a killable per-task process."""

    def __init__(
        self,
        *,
        device: str = "auto",
        runner: Any = subprocess.run,
        python_command: str = sys.executable,
        audio_speed: float = 1.0,
        silence_window_seconds: float = 0.8,
        silence_top_percent: float = 10.0,
        silence_threshold_ratio: float = 0.1,
        tail_window_seconds: float = 0.02,
        limiter: Any | None = None,
    ) -> None:
        self.device = device
        self.runner = runner
        self.python_command = python_command
        self.audio_speed = audio_speed
        self.silence_window_seconds = silence_window_seconds
        self.silence_top_percent = silence_top_percent
        self.silence_threshold_ratio = silence_threshold_ratio
        self.tail_window_seconds = tail_window_seconds
        self.limiter = limiter or threading.BoundedSemaphore(1)

    def align(
        self,
        audio_path: Path,
        tokens: list[str],
        timeout_seconds: float,
        *,
        line_token_counts: list[int],
    ) -> list[MMSMoraSpan]:
        request_id = uuid.uuid4().hex
        request_path = audio_path.parent / f".mms-{request_id}.request.json"
        output_path = audio_path.parent / f".mms-{request_id}.output.json"
        request_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path.resolve()),
                    "tokens": tokens,
                    "line_token_counts": line_token_counts,
                    "audio_speed": self.audio_speed,
                    "silence_window_seconds": self.silence_window_seconds,
                    "silence_top_percent": self.silence_top_percent,
                    "silence_threshold_ratio": self.silence_threshold_ratio,
                    "tail_window_seconds": self.tail_window_seconds,
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        command = [
            self.python_command,
            "-m",
            "app.alignment.mms_worker",
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--device",
            self.device,
        ]
        try:
            with self.limiter:
                self.runner(
                    command,
                    timeout=timeout_seconds,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            return [
                MMSMoraSpan(
                    start_ms=int(span["start_ms"]),
                    end_ms=int(span["end_ms"]),
                    score=float(span["score"]),
                )
                for span in payload["spans"]
            ]
        except subprocess.TimeoutExpired as exc:
            raise ForcedAlignmentError(
                "MMS_FA alignment timed out",
                timeout_seconds=timeout_seconds,
                stderr_tail=str(exc.stderr or "")[-1200:],
                command=command,
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            if detail:
                detail = detail[-1200:]
                raise ForcedAlignmentError(
                    f"MMS_FA worker failed: {detail}",
                    exit_code=exc.returncode,
                    stderr_tail=detail,
                    command=command,
                ) from exc
            raise ForcedAlignmentError(
                f"MMS_FA worker exited with code {exc.returncode}",
                exit_code=exc.returncode,
                command=command,
            ) from exc
        except Exception as exc:
            raise ForcedAlignmentError("MMS_FA worker failed") from exc
        finally:
            request_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class _MoraTarget:
    line_index: int
    token_index: int
    reading: str
    pronunciation: str | None = None


class MMSForcedAligner:
    """Map FA-Kara-style MMS forced-alignment spans to Nicokara moras."""

    requires_vocals = True

    def __init__(
        self,
        *,
        runtime: Any,
        timeout_seconds: float = 600,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        max_mora_duration_ms: int = DEFAULT_MAX_MORA_DURATION_MS,
    ) -> None:
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.min_confidence = min_confidence
        self.max_mora_duration_ms = max_mora_duration_ms

    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument | None,
        *,
        audio_path: Path,
    ) -> LyricTimeline:
        del transcript
        targets = self._targets(lyrics)
        if not targets:
            raise ForcedAlignmentError("Lyrics contain no alignable moras")
        tokens = self._romanized_tokens(targets)
        line_token_counts = [
            sum(target.line_index == line_index for target in targets)
            for line_index in range(len(lyrics.lines))
        ]
        spans = self.runtime.align(
            audio_path,
            tokens,
            self.timeout_seconds,
            line_token_counts=line_token_counts,
        )
        if len(spans) != len(targets):
            raise ForcedAlignmentError(
                "MMS_FA span count does not match the lyric mora count"
            )
        self._validate_spans(spans, line_token_counts)
        confidence = sum(span.score for span in spans) / len(spans)
        if confidence < self.min_confidence:
            raise ForcedAlignmentError(
                "MMS_FA confidence is below the usable threshold "
                f"({confidence:.3f} < {self.min_confidence:.3f})"
            )
        return close_mora_gaps(self._timeline(lyrics, targets, spans))

    @staticmethod
    def _targets(lyrics: LyricDocument) -> list[_MoraTarget]:
        targets: list[_MoraTarget] = []
        for line_index, line in enumerate(lyrics.lines):
            for token_index, token in enumerate(line.tokens):
                if token.alignment_pronunciation is not None:
                    targets.append(
                        _MoraTarget(
                            line_index,
                            token_index,
                            token.reading,
                            token.alignment_pronunciation,
                        )
                    )
                    continue
                if _LATIN_OR_DIGIT.search(token.surface):
                    raise ForcedAlignmentError(
                        "Unannotated Latin letters or digits require the "
                        "FA-Kara [surface|romaji] syntax"
                    )
                targets.extend(
                    _MoraTarget(line_index, token_index, mora)
                    for mora in split_moras(normalize_reading(token.reading))
                )
        return targets

    @staticmethod
    def _romanized_tokens(targets: list[_MoraTarget]) -> list[str]:
        raw = []
        for target in targets:
            if target.pronunciation is not None:
                raw.append(
                    _ROMAJI_FILTER.sub("", target.pronunciation.lower())
                )
            else:
                converted = "".join(
                    item["hepburn"]
                    for item in _CONVERTER.convert(target.reading)
                ).lower()
                raw.append(_ROMAJI_FILTER.sub("", converted))

        tokens: list[str] = []
        for index, token in enumerate(raw):
            target = targets[index]
            reading = target.reading
            if target.pronunciation is not None:
                pass
            elif reading == "っ":
                following = raw[index + 1] if index + 1 < len(raw) else ""
                token = following[:1] or "t"
            elif reading == "ー":
                previous = tokens[-1] if tokens else ""
                token = next(
                    (char for char in reversed(previous) if char in "aeiou"),
                    "u",
                )
            if not token:
                raise ForcedAlignmentError(
                    f"Mora cannot be romanized for MMS_FA: {reading!r}"
                )
            tokens.append(token)
        return tokens

    def _validate_spans(
        self,
        spans: list[MMSMoraSpan],
        line_token_counts: list[int],
    ) -> None:
        previous_end = 0
        for span in spans:
            if (
                span.start_ms < previous_end
                or span.end_ms < span.start_ms
                or not 0 <= span.score <= 1
            ):
                raise ForcedAlignmentError("MMS_FA returned invalid spans")
            if span.end_ms == span.start_ms:
                raise ForcedAlignmentError(
                    "MMS_FA returned a zero-duration mora span"
                )
            if span.end_ms - span.start_ms > self.max_mora_duration_ms:
                raise ForcedAlignmentError(
                    "MMS_FA mora duration exceeds the usable limit"
                )
            previous_end = span.end_ms

        offset = 0
        for line_index, count in enumerate(line_token_counts, start=1):
            if count <= 0:
                continue
            line_spans = spans[offset : offset + count]
            offset += count
            confidence = sum(span.score for span in line_spans) / count
            if confidence < self.min_confidence:
                raise ForcedAlignmentError(
                    f"MMS_FA line {line_index} confidence is below the "
                    f"usable threshold ({confidence:.3f} < "
                    f"{self.min_confidence:.3f})"
                )

    @staticmethod
    def _timeline(
        lyrics: LyricDocument,
        targets: list[_MoraTarget],
        spans: list[MMSMoraSpan],
    ) -> LyricTimeline:
        lines: list[AlignedLine] = []
        span_offset = 0
        for line_index, line in enumerate(lyrics.lines):
            aligned_tokens: list[AlignedToken] = []
            for token_index, token in enumerate(line.tokens):
                count = sum(
                    target.line_index == line_index
                    and target.token_index == token_index
                    for target in targets
                )
                token_targets = targets[span_offset : span_offset + count]
                token_spans = spans[span_offset : span_offset + count]
                span_offset += count
                moras = [
                    AlignedMora(
                        reading=target.reading,
                        start_ms=span.start_ms,
                        end_ms=span.end_ms,
                        matched=True,
                        confidence=span.score,
                    )
                    for target, span in zip(
                        token_targets,
                        token_spans,
                        strict=True,
                    )
                ]
                if moras:
                    start_ms = moras[0].start_ms
                    end_ms = moras[-1].end_ms
                    confidence = sum(m.confidence for m in moras) / len(moras)
                else:
                    anchor = aligned_tokens[-1].end_ms if aligned_tokens else 0
                    start_ms = end_ms = anchor
                    confidence = 1.0
                aligned_tokens.append(
                    AlignedToken(
                        surface=token.surface,
                        reading=token.reading,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=confidence,
                        moras=moras,
                    )
                )
            if not aligned_tokens:
                continue
            lines.append(
                AlignedLine(
                    surface=line.surface,
                    reading=line.reading,
                    start_ms=aligned_tokens[0].start_ms,
                    end_ms=aligned_tokens[-1].end_ms,
                    confidence=(
                        sum(token.confidence for token in aligned_tokens)
                        / len(aligned_tokens)
                    ),
                    tokens=aligned_tokens,
                )
            )

        confidence = sum(span.score for span in spans) / len(spans)
        warnings = ["mms_low_confidence"] if confidence < 0.5 else []
        return LyricTimeline(
            confidence=confidence,
            lines=lines,
            warnings=warnings,
            alignment_engine="fa_kara_mms",
            alignment_model=MMS_MODEL_NAME,
        )
