from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

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
    audio_path.write_bytes(b"wav")
    transcriber = whisper_module.FasterWhisperTranscriber(
        model_name="small",
        device="cpu",
        compute_type="int8",
        model_factory=model_factory,
    )

    transcript = transcriber.transcribe(audio_path)

    assert created_with == [("small", "cpu", "int8")]
    assert fake_model.calls == [
        (
            str(audio_path),
            {
                "language": "ja",
                "beam_size": 5,
                "vad_filter": False,
                "word_timestamps": True,
                "condition_on_previous_text": False,
            },
        )
    ]
    assert transcript.language == "ja"
    assert transcript.language_probability == pytest.approx(0.99)
    assert transcript.duration_seconds == pytest.approx(180.5)
    assert transcript.text == "君の知らない物語"
    assert transcript.segments[0].start_ms == 1250
    assert transcript.segments[0].end_ms == 3500
    assert transcript.segments[0].words[0].text == "君の"
    assert transcript.segments[0].words[0].start_ms == 1250
    assert transcript.segments[0].words[1].confidence == pytest.approx(0.91)
