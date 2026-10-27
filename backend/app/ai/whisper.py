from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import gcd
from pathlib import Path
import wave

import numpy as np
from scipy.signal import resample_poly
from app.core.processing_control import check_interrupted
from typing import Any, Callable


def milliseconds(seconds: float) -> int:
    return round(seconds * 1000)


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start_ms: int
    end_ms: int
    confidence: float


@dataclass(frozen=True)
class TranscriptSegment:
    id: int
    text: str
    start_ms: int
    end_ms: int
    confidence: float
    no_speech_probability: float
    words: list[TranscriptWord] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptDocument:
    language: str
    language_probability: float
    duration_seconds: float
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def transcript_document_from_dict(value: dict[str, Any]) -> TranscriptDocument:
    return TranscriptDocument(
        language=str(value["language"]),
        language_probability=float(value["language_probability"]),
        duration_seconds=float(value["duration_seconds"]),
        text=str(value["text"]),
        segments=[
            TranscriptSegment(
                id=int(segment["id"]),
                text=str(segment["text"]),
                start_ms=int(segment["start_ms"]),
                end_ms=int(segment["end_ms"]),
                confidence=float(segment["confidence"]),
                no_speech_probability=float(
                    segment["no_speech_probability"]
                ),
                words=[
                    TranscriptWord(
                        text=str(word["text"]),
                        start_ms=int(word["start_ms"]),
                        end_ms=int(word["end_ms"]),
                        confidence=float(word["confidence"]),
                    )
                    for word in segment.get("words", [])
                ],
            )
            for segment in value.get("segments", [])
        ],
    )


ModelFactory = Callable[[str, str, str], Any]


def load_pcm16_mono(audio_path: Path) -> np.ndarray:
    """Normalize a project-generated PCM WAV without invoking PyAV."""
    with wave.open(str(audio_path), "rb") as audio:
        channels = audio.getnchannels()
        sample_rate = audio.getframerate()
        if channels < 1 or audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise ValueError("Whisper analysis audio must be PCM16 WAV")
        frames = audio.readframes(audio.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples /= 32768.0
    if sample_rate != 16_000 and samples.size:
        divisor = gcd(sample_rate, 16_000)
        samples = resample_poly(
            samples,
            16_000 // divisor,
            sample_rate // divisor,
        )
    return np.asarray(samples, dtype=np.float32)


def default_model_factory(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device=device, compute_type=compute_type)


class FasterWhisperTranscriber:
    def __init__(
        self,
        *,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        model_factory: ModelFactory = default_model_factory,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_factory = model_factory
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = self.model_factory(
                self.model_name,
                self.device,
                self.compute_type,
            )
        return self._model

    def transcribe(self, audio_path: Path) -> TranscriptDocument:
        check_interrupted()
        audio = load_pcm16_mono(audio_path)
        raw_segments, info = self.model.transcribe(
            audio,
            language="ja",
            beam_size=5,
            vad_filter=False,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        segments: list[TranscriptSegment] = []
        for raw_segment in raw_segments:
            check_interrupted()
            words = [
                TranscriptWord(
                    text=word.word.strip(),
                    start_ms=milliseconds(word.start),
                    end_ms=milliseconds(word.end),
                    confidence=float(word.probability),
                )
                for word in (raw_segment.words or [])
            ]
            segments.append(
                TranscriptSegment(
                    id=int(raw_segment.id),
                    text=raw_segment.text.strip(),
                    start_ms=milliseconds(raw_segment.start),
                    end_ms=milliseconds(raw_segment.end),
                    confidence=float(raw_segment.avg_logprob),
                    no_speech_probability=float(raw_segment.no_speech_prob),
                    words=words,
                )
            )
        return TranscriptDocument(
            language=info.language,
            language_probability=float(info.language_probability),
            duration_seconds=float(info.duration),
            text="".join(segment.text for segment in segments),
            segments=segments,
        )
