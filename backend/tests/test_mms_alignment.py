from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest

from app.ai.whisper import TranscriptDocument
from app.alignment.models import LyricTimeline
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


def empty_transcript() -> TranscriptDocument:
    return TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=4.0,
        text="",
        segments=[],
    )


def test_mms_aligner_maps_romanized_spans_to_existing_mora_timeline(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import MMSForcedAligner, MMSMoraSpan

    class RecordingRuntime:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, list[str], float]] = []

        def align(
            self,
            audio_path: Path,
            tokens: list[str],
            timeout_seconds: float,
        ) -> list[MMSMoraSpan]:
            self.calls.append((audio_path, tokens, timeout_seconds))
            return [
                MMSMoraSpan(start_ms=1000, end_ms=1180, score=0.91),
                MMSMoraSpan(start_ms=1180, end_ms=1390, score=0.88),
                MMSMoraSpan(start_ms=1390, end_ms=1600, score=0.95),
            ]

    runtime = RecordingRuntime()
    audio_path = tmp_path / "vocals.wav"
    audio_path.write_bytes(b"vocals")

    timeline = MMSForcedAligner(
        runtime=runtime,
        timeout_seconds=42,
    ).align(sample_lyrics(), empty_transcript(), audio_path=audio_path)

    assert runtime.calls == [(audio_path, ["ki", "mi", "no"], 42)]
    assert timeline.alignment_engine == "fa_kara_mms"
    assert timeline.alignment_model == "torchaudio.pipelines.MMS_FA"
    assert timeline.lines[0].start_ms == 1000
    assert timeline.lines[0].end_ms == 1600
    assert [
        (mora.reading, mora.start_ms, mora.end_ms)
        for token in timeline.lines[0].tokens
        for mora in token.moras
    ] == [
        ("き", 1000, 1180),
        ("み", 1180, 1390),
        ("の", 1390, 1600),
    ]
    assert timeline.confidence == pytest.approx((0.91 + 0.88 + 0.95) / 3)


def test_resilient_aligner_falls_back_and_records_actual_engine(
    tmp_path: Path,
) -> None:
    from app.alignment.engine import ResilientAlignmentEngine
    from app.alignment.mms import ForcedAlignmentError

    class FailingPrimary:
        requires_vocals = True

        def align(self, lyrics, transcript, *, audio_path):
            raise ForcedAlignmentError("MMS_FA timed out")

    class Fallback:
        def align(self, lyrics, transcript):
            return LyricTimeline(
                confidence=0.7,
                alignment_engine="whisper_mora",
            )

    timeline = ResilientAlignmentEngine(
        primary=FailingPrimary(),
        fallback=Fallback(),
    ).align(
        sample_lyrics(),
        empty_transcript(),
        audio_path=tmp_path / "vocals.wav",
    )

    assert timeline.alignment_engine == "whisper_mora"
    assert timeline.warnings == ["fa_kara_fallback:ForcedAlignmentError"]


def test_mms_aligner_rejects_incomplete_span_output(tmp_path: Path) -> None:
    from app.alignment.mms import (
        ForcedAlignmentError,
        MMSForcedAligner,
        MMSMoraSpan,
    )

    class IncompleteRuntime:
        def align(self, audio_path, tokens, timeout_seconds):
            return [MMSMoraSpan(start_ms=1000, end_ms=1200, score=0.9)]

    with pytest.raises(ForcedAlignmentError, match="span count"):
        MMSForcedAligner(runtime=IncompleteRuntime()).align(
            sample_lyrics(),
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_subprocess_runtime_parses_worker_output(tmp_path: Path) -> None:
    from app.alignment.mms import SubprocessMMSRuntime

    recorded: dict[str, object] = {}

    def runner(command, *, timeout, check, capture_output, text):
        recorded.update(
            command=command,
            timeout=timeout,
            check=check,
            capture_output=capture_output,
            text=text,
        )
        request_index = command.index("--request") + 1
        output_index = command.index("--output") + 1
        request_path = Path(command[request_index])
        output_path = Path(command[output_index])
        recorded["request"] = json.loads(
            request_path.read_text(encoding="utf-8")
        )
        output_path.write_text(
            json.dumps(
                {
                    "spans": [
                        {"start_ms": 10, "end_ms": 90, "score": 0.75},
                        {"start_ms": 90, "end_ms": 180, "score": 0.8},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    audio_path = tmp_path / "audio_vocals.wav"
    audio_path.write_bytes(b"vocals")
    spans = SubprocessMMSRuntime(
        device="cpu",
        runner=runner,
        python_command="python-test",
    ).align(audio_path, ["ki", "mi"], 12)

    assert recorded["timeout"] == 12
    assert recorded["request"] == {
        "audio_path": str(audio_path.resolve()),
        "tokens": ["ki", "mi"],
    }
    assert [(span.start_ms, span.end_ms, span.score) for span in spans] == [
        (10, 90, 0.75),
        (90, 180, 0.8),
    ]
    assert not (tmp_path / "mms-request.json").exists()


def test_subprocess_runtime_turns_timeout_into_safe_fallback_error(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, SubprocessMMSRuntime

    def timing_out_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    audio_path = tmp_path / "audio_vocals.wav"
    audio_path.write_bytes(b"vocals")

    with pytest.raises(ForcedAlignmentError, match="timed out"):
        SubprocessMMSRuntime(
            runner=timing_out_runner,
            python_command="python-test",
        ).align(audio_path, ["ki"], 0.1)
