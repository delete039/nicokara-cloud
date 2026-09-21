from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.alignment.models import LyricTimeline
from app.ai.whisper import TranscriptDocument
from app.lyrics.models import LyricDocument, LyricLine, LyricToken


def sample_lyrics() -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="君の",
        lines=[
            LyricLine(
                source="君の",
                surface="君の",
                reading="きみの",
                tokens=[
                    LyricToken(surface="君", reading="きみ"),
                    LyricToken(surface="の", reading="の"),
                ],
            )
        ],
    )


def test_yohane_aligner_maps_token_spans_to_mora_timeline(tmp_path: Path) -> None:
    from app.alignment.yohane import YohaneForcedAligner, YohaneMoraSpan

    class Runtime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            assert tokens == ["ki", "mi", "no"]
            assert line_token_counts == [3]
            return [
                YohaneMoraSpan(1000, 1150, 0.91),
                YohaneMoraSpan(1180, 1350, 0.88),
                YohaneMoraSpan(1390, 1600, 0.95),
            ]

    timeline = YohaneForcedAligner(runtime=Runtime(), timeout_seconds=42).align(
        sample_lyrics(), None, audio_path=tmp_path / "vocals.wav"
    )

    assert timeline.alignment_engine == "fa_kara_yohane"
    assert timeline.alignment_model == "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
    assert timeline.lines[0].start_ms == 1000
    assert timeline.lines[0].end_ms == 1600
    assert [
        (mora.reading, mora.start_ms, mora.end_ms)
        for token in timeline.lines[0].tokens
        for mora in token.moras
    ] == [("き", 1000, 1180), ("み", 1180, 1390), ("の", 1390, 1600)]


def test_yohane_rejects_pathological_long_mora_span(tmp_path: Path) -> None:
    from app.alignment.mms import ForcedAlignmentError
    from app.alignment.yohane import YohaneForcedAligner, YohaneMoraSpan

    class Runtime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            return [
                YohaneMoraSpan(1000, 10000, 0.91),
                YohaneMoraSpan(10000, 10150, 0.88),
                YohaneMoraSpan(10150, 10300, 0.95),
            ]

    with pytest.raises(ForcedAlignmentError, match="mora duration exceeds"):
        YohaneForcedAligner(runtime=Runtime()).align(
            sample_lyrics(), None, audio_path=tmp_path / "vocals.wav"
        )


def test_yohane_preserves_low_confidence_output_with_yohane_warning(
    tmp_path: Path,
) -> None:
    from app.alignment.yohane import YohaneForcedAligner, YohaneMoraSpan

    class Runtime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            return [
                YohaneMoraSpan(index * 200, (index + 1) * 200, 0.05)
                for index, _ in enumerate(tokens)
            ]

    timeline = YohaneForcedAligner(runtime=Runtime(), min_confidence=0.10).align(
        sample_lyrics(), None, audio_path=tmp_path / "vocals.wav"
    )

    assert "yohane_low_confidence" in timeline.warnings
    assert "yohane_low_confidence_line:1" in timeline.warnings
    assert all(not warning.startswith("mms_") for warning in timeline.warnings)


def test_yohane_runtime_serializes_request_and_output(tmp_path: Path) -> None:
    from app.alignment.yohane import SubprocessYohaneRuntime

    recorded: dict[str, object] = {}

    def runner(command, **kwargs):
        recorded["command"] = command
        request_path = Path(command[command.index("--request") + 1])
        output_path = Path(command[command.index("--output") + 1])
        recorded["request"] = json.loads(request_path.read_text(encoding="utf-8"))
        output_path.write_text(
            json.dumps({"spans": [{"start_ms": 10, "end_ms": 90, "score": 0.8}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    spans = SubprocessYohaneRuntime(
        source_dir=tmp_path / "FA-Kara",
        model_dir=tmp_path / "yohane",
        runner=runner,
        python_command="python-test",
    ).align(audio, ["ki"], 12, line_token_counts=[1])

    assert recorded["request"] == {
        "audio_path": str(audio.resolve()),
        "tokens": ["ki"],
        "line_token_counts": [1],
        "audio_speed": 1.0,
    }
    assert [(span.start_ms, span.end_ms, span.score) for span in spans] == [(10, 90, 0.8)]
    assert not list(tmp_path.glob(".yohane-*.request.json"))


def test_resilient_engine_routes_multivoice_to_yohane_then_mms() -> None:
    from app.alignment.engine import ResilientAlignmentEngine

    class Primary:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.7, alignment_engine="fa_kara_mms")

    class Yohane:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.9, alignment_engine="fa_kara_yohane")

    class Fallback:
        def align(self, lyrics, transcript):
            return LyricTimeline(confidence=0.1, alignment_engine="whisper_mora")

    engine = ResilientAlignmentEngine(
        primary=Primary(), fallback=Fallback(), multivoice_primary=Yohane()
    )
    result = engine.align(sample_lyrics(), TranscriptDocument("ja", 1.0, 1.0, "", []), audio_path=Path("x.wav"), alignment_mode="multivoice")

    assert result.alignment_engine == "fa_kara_yohane"


def test_resilient_engine_auto_prefers_yohane() -> None:
    from app.alignment.engine import ResilientAlignmentEngine

    class Primary:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.7, alignment_engine="fa_kara_mms")

    class Yohane:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.9, alignment_engine="fa_kara_yohane")

    class Fallback:
        def align(self, lyrics, transcript):
            return LyricTimeline(confidence=0.1, alignment_engine="whisper_mora")

    result = ResilientAlignmentEngine(
        primary=Primary(), fallback=Fallback(), multivoice_primary=Yohane()
    ).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("x.wav"),
        alignment_mode="auto",
    )

    assert result.alignment_engine == "fa_kara_yohane"


def test_resilient_engine_uses_original_mix_for_alignment_input() -> None:
    from app.alignment.engine import ResilientAlignmentEngine

    engine = ResilientAlignmentEngine(
        primary=object(), fallback=object(), multivoice_primary=object()
    )

    assert engine.requires_vocals is False


def test_yohane_worker_passes_multichannel_waveform_to_upstream_aligner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.alignment.yohane_worker import align_audio

    class Waveform:
        channels = 2

        def mean(self, **kwargs):
            raise AssertionError("worker must not mix audio before FA-Kara")

    class FakeModel:
        def to(self, device):
            return self

    class FakeAligner:
        def __init__(self, model_dir):
            self.device = None
            self.model = FakeModel()

        def tokenize(self, tokens):
            return [[1] for _ in tokens]

        def align(self, token_ids, waveform, sample_rate):
            assert waveform.channels == 2
            return None, [[types.SimpleNamespace(start=1, end=2, score=0.8)]], 16000

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        device=lambda name: name,
    )
    fake_torchaudio = types.SimpleNamespace(
        load=lambda path: (Waveform(), 16000),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)
    monkeypatch.setitem(
        sys.modules,
        "align_yohane",
        types.SimpleNamespace(Wav2Vec2ForcedAligner=FakeAligner),
    )
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    model_dir = tmp_path / "model"
    source_dir = tmp_path / "source"
    model_dir.mkdir()
    source_dir.mkdir()

    result = align_audio(
        audio_path,
        ["ki"],
        model_dir=model_dir,
        source_dir=source_dir,
        device_name="cpu",
        audio_speed=1.0,
    )

    assert result == [{"start_ms": 20, "end_ms": 40, "score": 0.8}]


def test_resilient_engine_marks_multivoice_quality_fallback() -> None:
    from app.alignment.engine import ResilientAlignmentEngine
    from app.alignment.mms import ForcedAlignmentError

    class Primary:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.7, alignment_engine="fa_kara_mms")

    class Yohane:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            raise ForcedAlignmentError("MMS_FA mora duration exceeds the usable limit")

    class Fallback:
        def align(self, lyrics, transcript):
            return LyricTimeline(confidence=0.1, alignment_engine="whisper_mora")

    result = ResilientAlignmentEngine(
        primary=Primary(), fallback=Fallback(), multivoice_primary=Yohane()
    ).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("x.wav"),
        alignment_mode="multivoice",
    )

    assert result.alignment_engine == "fa_kara_mms"
    assert "multivoice_yohane_quality_fallback" in result.warnings


def test_resilient_engine_routes_robust_mode_to_dual_aligner() -> None:
    from app.alignment.engine import ResilientAlignmentEngine

    class Primary:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(confidence=0.7, alignment_engine="fa_kara_mms")

    class Robust:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            return LyricTimeline(
                confidence=0.8,
                alignment_engine="fa_kara_robust_dual",
            )

    class Fallback:
        def align(self, lyrics, transcript):
            return LyricTimeline(confidence=0.1, alignment_engine="whisper_mora")

    result = ResilientAlignmentEngine(
        primary=Primary(), fallback=Fallback(), robust_primary=Robust()
    ).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("x.wav"),
        alignment_mode="robust",
    )

    assert result.alignment_engine == "fa_kara_robust_dual"
