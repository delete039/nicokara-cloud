from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np
import pytest


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def transcribe(self, path: str, **options):
        self.calls.append((path, options))
        segments = [
            SimpleNamespace(
                id=0,
                start=1.25,
                end=3.5,
                text=" 君の知らない物語",
                avg_logprob=-0.2,
                no_speech_prob=0.01,
                words=[
                    SimpleNamespace(
                        start=1.25,
                        end=1.8,
                        word="君の",
                        probability=0.94,
                    ),
                    SimpleNamespace(
                        start=1.8,
                        end=3.5,
                        word="知らない物語",
                        probability=0.91,
                    ),
                ],
            )
        ]
        info = SimpleNamespace(
            language="ja",
            language_probability=0.99,
            duration=180.5,
        )
        return iter(segments), info


def test_transcribes_japanese_with_word_timestamps(tmp_path: Path) -> None:
    try:
        whisper_module = importlib.import_module("app.ai.whisper")
    except ModuleNotFoundError:
        pytest.fail("Whisper transcription module is not implemented")

    fake_model = FakeWhisperModel()
    created_with: list[tuple[str, str, str]] = []

    def model_factory(model_name: str, device: str, compute_type: str):
        created_with.append((model_name, device, compute_type))
        return fake_model

    audio_path = tmp_path / "audio.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 160)
    transcriber = whisper_module.FasterWhisperTranscriber(
        model_name="small",
        device="cpu",
        compute_type="int8",
        model_factory=model_factory,
    )

    transcript = transcriber.transcribe(audio_path)

    assert created_with == [("small", "cpu", "int8")]
    whisper_input, options = fake_model.calls[0]
    assert isinstance(whisper_input, np.ndarray)
    assert whisper_input.shape == (160,)
    assert options == {
        "language": "ja",
        "beam_size": 5,
        "vad_filter": False,
        "word_timestamps": True,
        "condition_on_previous_text": False,
    }
    assert transcript.language == "ja"
    assert transcript.language_probability == pytest.approx(0.99)
    assert transcript.duration_seconds == pytest.approx(180.5)
    assert transcript.text == "君の知らない物語"
    assert transcript.segments[0].start_ms == 1250
    assert transcript.segments[0].end_ms == 3500
    assert transcript.segments[0].words[0].text == "君の"
    assert transcript.segments[0].words[0].start_ms == 1250
    assert transcript.segments[0].words[1].confidence == pytest.approx(0.91)


def test_transcriber_passes_standard_pcm_to_whisper_without_pyav(
    tmp_path: Path,
) -> None:
    whisper_module = importlib.import_module("app.ai.whisper")
    fake_model = FakeWhisperModel()
    audio_path = tmp_path / "analysis.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(np.array([-32768, 0, 16384, 32767], dtype="<i2").tobytes())

    transcriber = whisper_module.FasterWhisperTranscriber(
        model_factory=lambda *_: fake_model,
    )
    transcriber.transcribe(audio_path)

    whisper_input, _ = fake_model.calls[0]
    assert isinstance(whisper_input, np.ndarray)
    assert whisper_input.dtype == np.float32
    assert whisper_input.tolist() == pytest.approx([-1.0, 0.0, 0.5, 32767 / 32768])


def test_transcriber_mixes_and_resamples_vocal_stem_without_pyav(
    tmp_path: Path,
) -> None:
    whisper_module = importlib.import_module("app.ai.whisper")
    fake_model = FakeWhisperModel()
    audio_path = tmp_path / "vocals.wav"
    stereo_frames = np.array(
        [[-32768, 32767], [-16384, 16384], [0, 0], [16384, -16384]],
        dtype="<i2",
    )
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(stereo_frames.tobytes())

    transcriber = whisper_module.FasterWhisperTranscriber(
        model_factory=lambda *_: fake_model,
    )
    transcriber.transcribe(audio_path)

    whisper_input, _ = fake_model.calls[0]
    assert isinstance(whisper_input, np.ndarray)
    assert whisper_input.dtype == np.float32
    assert whisper_input.shape == (8,)
    assert np.isfinite(whisper_input).all()
