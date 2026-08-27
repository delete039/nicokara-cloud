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
            *,
            line_token_counts: list[int],
        ) -> list[MMSMoraSpan]:
            self.calls.append((audio_path, tokens, timeout_seconds))
            assert line_token_counts == [3]
            return [
                MMSMoraSpan(start_ms=1000, end_ms=1150, score=0.91),
                MMSMoraSpan(start_ms=1180, end_ms=1350, score=0.88),
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
    caplog: pytest.LogCaptureFixture,
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
    assert "MMS_FA timed out" in caplog.text


def test_resilient_aligner_does_not_load_transcript_when_mms_succeeds(
    tmp_path: Path,
) -> None:
    from app.alignment.engine import ResilientAlignmentEngine

    class SuccessfulPrimary:
        def align(self, lyrics, transcript, *, audio_path):
            assert transcript is None
            return LyricTimeline(
                confidence=1.0,
                alignment_engine="fa_kara_mms",
            )

    class UnexpectedFallback:
        def align(self, lyrics, transcript):
            pytest.fail("Whisper fallback must not run after MMS succeeds")

    def unexpected_transcript_factory() -> TranscriptDocument:
        pytest.fail("MMS must run before a Whisper transcript is requested")

    timeline = ResilientAlignmentEngine(
        primary=SuccessfulPrimary(),
        fallback=UnexpectedFallback(),
    ).align(
        sample_lyrics(),
        None,
        audio_path=tmp_path / "vocals.wav",
        transcript_factory=unexpected_transcript_factory,
    )

    assert timeline.alignment_engine == "fa_kara_mms"


def test_resilient_aligner_loads_transcript_only_after_mms_fails(
    tmp_path: Path,
) -> None:
    from app.alignment.engine import ResilientAlignmentEngine
    from app.alignment.mms import ForcedAlignmentError

    transcript = empty_transcript()
    factory_calls = 0

    class FailingPrimary:
        def align(self, lyrics, supplied_transcript, *, audio_path):
            assert supplied_transcript is None
            raise ForcedAlignmentError("MMS_FA unavailable")

    class RecordingFallback:
        def align(self, lyrics, supplied_transcript):
            assert supplied_transcript is transcript
            return LyricTimeline(
                confidence=0.6,
                alignment_engine="whisper_mora",
            )

    def transcript_factory() -> TranscriptDocument:
        nonlocal factory_calls
        factory_calls += 1
        return transcript

    timeline = ResilientAlignmentEngine(
        primary=FailingPrimary(),
        fallback=RecordingFallback(),
    ).align(
        sample_lyrics(),
        None,
        audio_path=tmp_path / "vocals.wav",
        transcript_factory=transcript_factory,
    )

    assert factory_calls == 1
    assert timeline.alignment_engine == "whisper_mora"
    assert timeline.warnings == ["fa_kara_fallback:ForcedAlignmentError"]


def test_mms_aligner_rejects_incomplete_span_output(tmp_path: Path) -> None:
    from app.alignment.mms import (
        ForcedAlignmentError,
        MMSForcedAligner,
        MMSMoraSpan,
    )

    class IncompleteRuntime:
        def align(
            self,
            audio_path,
            tokens,
            timeout_seconds,
            *,
            line_token_counts,
        ):
            return [MMSMoraSpan(start_ms=1000, end_ms=1200, score=0.9)]

    with pytest.raises(ForcedAlignmentError, match="span count"):
        MMSForcedAligner(runtime=IncompleteRuntime()).align(
            sample_lyrics(),
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_mms_aligner_rejects_low_confidence_span_output(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import (
        ForcedAlignmentError,
        MMSForcedAligner,
        MMSMoraSpan,
    )

    class LowConfidenceRuntime:
        def align(
            self,
            audio_path,
            tokens,
            timeout_seconds,
            *,
            line_token_counts,
        ):
            return [
                MMSMoraSpan(
                    start_ms=1000 + index * 200,
                    end_ms=1200 + index * 200,
                    score=0.1,
                )
                for index in range(len(tokens))
            ]

    with pytest.raises(ForcedAlignmentError, match="confidence"):
        MMSForcedAligner(runtime=LowConfidenceRuntime()).align(
            sample_lyrics(),
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_mms_aligner_uses_fa_kara_explicit_pronunciation(tmp_path: Path) -> None:
    from app.alignment.mms import MMSForcedAligner, MMSMoraSpan

    lyrics = LyricDocument(
        provider="local",
        source_text="[の|n]",
        lines=[
            LyricLine(
                source="[の|n]",
                surface="の",
                reading="の",
                tokens=[
                    LyricToken(
                        surface="の",
                        reading="の",
                        alignment_pronunciation="n",
                    )
                ],
            )
        ],
    )

    class RecordingRuntime:
        def __init__(self) -> None:
            self.tokens: list[str] = []
            self.line_token_counts: list[int] = []

        def align(
            self,
            audio_path,
            tokens,
            timeout_seconds,
            *,
            line_token_counts,
        ):
            self.tokens = tokens
            self.line_token_counts = line_token_counts
            return [MMSMoraSpan(start_ms=100, end_ms=200, score=0.9)]

    runtime = RecordingRuntime()
    MMSForcedAligner(runtime=runtime).align(
        lyrics,
        empty_transcript(),
        audio_path=tmp_path / "vocals.wav",
    )

    assert runtime.tokens == ["n"]
    assert runtime.line_token_counts == [1]


def test_mms_aligner_falls_back_for_unannotated_latin_lyrics(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, MMSForcedAligner

    lyrics = LyricDocument(
        provider="local",
        source_text="More love",
        lines=[
            LyricLine(
                source="More love",
                surface="More love",
                reading="More love",
                tokens=[LyricToken(surface="More love", reading="More love")],
            )
        ],
    )

    with pytest.raises(ForcedAlignmentError, match="Latin"):
        MMSForcedAligner(runtime=object()).align(
            lyrics,
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


@pytest.mark.parametrize(
    ("surface", "reading", "expected_tokens"),
    [
        ("LOVE", "らぶ", ["ra", "bu"]),
        ("39", "さんきゅー", ["sa", "n", "kyuu"]),
    ],
)
def test_mms_aligner_accepts_latin_or_digits_with_reviewed_kana_reading(
    tmp_path: Path,
    surface: str,
    reading: str,
    expected_tokens: list[str],
) -> None:
    from app.alignment.japanese import normalize_reading, split_moras
    from app.alignment.mms import MMSForcedAligner, MMSMoraSpan

    lyrics = LyricDocument(
        provider="local",
        source_text=surface,
        lines=[
            LyricLine(
                source=surface,
                surface=surface,
                reading=reading,
                tokens=[LyricToken(surface=surface, reading=reading)],
            )
        ],
    )

    class RecordingRuntime:
        def __init__(self) -> None:
            self.tokens: list[str] = []

        def align(
            self,
            audio_path,
            tokens,
            timeout_seconds,
            *,
            line_token_counts,
        ):
            self.tokens = tokens
            assert line_token_counts == [len(expected_tokens)]
            return [
                MMSMoraSpan(
                    start_ms=100 + index * 100,
                    end_ms=200 + index * 100,
                    score=0.9,
                )
                for index in range(len(tokens))
            ]

    runtime = RecordingRuntime()
    timeline = MMSForcedAligner(runtime=runtime).align(
        lyrics,
        empty_transcript(),
        audio_path=tmp_path / "vocals.wav",
    )

    assert runtime.tokens == expected_tokens
    assert timeline.lines[0].surface == surface
    assert [
        mora.reading
        for token in timeline.lines[0].tokens
        for mora in token.moras
    ] == list(split_moras(normalize_reading(reading)))


def test_mms_aligner_romanizes_fa_kara_sokuon_unit_with_next_consonant() -> None:
    from app.alignment.mms import MMSForcedAligner, _MoraTarget

    targets = [
        _MoraTarget(0, 0, "げっ"),
        _MoraTarget(0, 1, "と"),
    ]

    assert MMSForcedAligner._romanized_tokens(targets) == ["get", "to"]


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
    ).align(
        audio_path,
        ["ki", "mi"],
        12,
        line_token_counts=[2],
    )

    assert recorded["timeout"] == 12
    assert recorded["request"] == {
        "audio_path": str(audio_path.resolve()),
        "tokens": ["ki", "mi"],
        "line_token_counts": [2],
        "audio_speed": 1.0,
        "silence_window_seconds": 0.8,
        "silence_top_percent": 10.0,
        "silence_threshold_ratio": 0.1,
        "tail_window_seconds": 0.02,
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
        ).align(audio_path, ["ki"], 0.1, line_token_counts=[1])


def test_subprocess_runtime_preserves_bounded_worker_diagnostics(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, SubprocessMMSRuntime

    def failing_runner(command, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="model cache is corrupt",
        )

    audio_path = tmp_path / "audio_vocals.wav"
    audio_path.write_bytes(b"vocals")

    with pytest.raises(
        ForcedAlignmentError,
        match="model cache is corrupt",
    ):
        SubprocessMMSRuntime(
            runner=failing_runner,
            python_command="python-test",
        ).align(audio_path, ["ki"], 10, line_token_counts=[1])


def test_fa_kara_time_mapping_restores_packed_audio_positions() -> None:
    from app.alignment.mms_worker import map_packed_time_ms

    ranges = [(1.0, 2.0), (4.0, 6.0)]

    assert map_packed_time_ms(0, ranges) == 1000
    assert map_packed_time_ms(500, ranges) == 1500
    assert map_packed_time_ms(1000, ranges) == 4000
    assert map_packed_time_ms(1250, ranges) == 4250
    assert map_packed_time_ms(4000, ranges) == 6000


def test_fa_kara_rms_detection_finds_the_vocal_region() -> None:
    import numpy as np

    from app.alignment.mms_worker import recognize_non_silent_ranges

    audio = np.zeros(4000, dtype=np.float32)
    audio[1000:2000] = 0.8

    ranges = recognize_non_silent_ranges(
        audio,
        1000,
        frame_seconds=0.2,
        top_percent=10,
        threshold_ratio=0.1,
    )

    assert ranges
    assert ranges[0][0] <= 1.0
    assert ranges[0][1] >= 2.0


def test_fa_kara_line_boundary_correction_uses_vocal_edges() -> None:
    from app.alignment.mms_worker import _adjust_line_boundaries

    spans = [
        {"start_ms": 900, "end_ms": 1100, "score": 0.9},
        {"start_ms": 1300, "end_ms": 1500, "score": 0.9},
    ]

    corrected = _adjust_line_boundaries(
        spans,
        [2],
        [(1.0, 2.0)],
        [(1.0, 1.7)],
    )

    assert corrected[0]["start_ms"] == 1000
    assert corrected[-1]["end_ms"] == 1700


def test_fa_kara_line_boundary_correction_does_not_collapse_first_mora() -> None:
    from app.alignment.mms_worker import _adjust_line_boundaries

    spans = [
        {"start_ms": 1000, "end_ms": 1100, "score": 0.9},
        {"start_ms": 4000, "end_ms": 4100, "score": 0.9},
    ]

    corrected = _adjust_line_boundaries(
        spans,
        [2],
        [(1.0, 1.2), (3.5, 4.5)],
        [],
    )

    assert corrected[0]["start_ms"] == 1000
    assert corrected[0]["end_ms"] == 1100


def test_mms_aligner_rejects_zero_duration_mora_spans(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, MMSForcedAligner, MMSMoraSpan

    class CollapsedRuntime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            return [
                MMSMoraSpan(start_ms=1000, end_ms=1000, score=0.95)
                for _ in tokens
            ]

    with pytest.raises(ForcedAlignmentError, match="zero-duration"):
        MMSForcedAligner(runtime=CollapsedRuntime()).align(
            sample_lyrics(),
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_mms_aligner_rejects_abnormally_long_mora_spans(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, MMSForcedAligner, MMSMoraSpan

    class LongSpanRuntime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            return [
                MMSMoraSpan(
                    start_ms=index * 20_000,
                    end_ms=(index + 1) * 20_000,
                    score=0.95,
                )
                for index, _ in enumerate(tokens)
            ]

    with pytest.raises(ForcedAlignmentError, match="duration"):
        MMSForcedAligner(runtime=LongSpanRuntime()).align(
            sample_lyrics(),
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_mms_aligner_rejects_a_low_confidence_line_hidden_by_global_average(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import ForcedAlignmentError, MMSForcedAligner, MMSMoraSpan

    lyrics = sample_lyrics()
    lyrics.lines.append(sample_lyrics().lines[0])

    class MixedConfidenceRuntime:
        def align(self, audio_path, tokens, timeout_seconds, *, line_token_counts):
            assert line_token_counts == [3, 3]
            return [
                MMSMoraSpan(
                    start_ms=index * 200,
                    end_ms=(index + 1) * 200,
                    score=0.05 if index < 3 else 0.95,
                )
                for index, _ in enumerate(tokens)
            ]

    with pytest.raises(ForcedAlignmentError, match="line 1 confidence"):
        MMSForcedAligner(runtime=MixedConfidenceRuntime()).align(
            lyrics,
            empty_transcript(),
            audio_path=tmp_path / "vocals.wav",
        )


def test_subprocess_runtime_uses_the_shared_alignment_limiter(
    tmp_path: Path,
) -> None:
    from app.alignment.mms import SubprocessMMSRuntime

    class RecordingLimiter:
        def __init__(self) -> None:
            self.entered = 0

        def __enter__(self):
            self.entered += 1
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.entered -= 1

    limiter = RecordingLimiter()

    def runner(command, **kwargs):
        assert limiter.entered == 1
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {"spans": [{"start_ms": 10, "end_ms": 90, "score": 0.9}]}
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    audio_path = tmp_path / "audio_vocals.wav"
    audio_path.write_bytes(b"vocals")
    runtime = SubprocessMMSRuntime(runner=runner, limiter=limiter)

    runtime.align(audio_path, ["ki"], 10, line_token_counts=[1])

    assert limiter.entered == 0
