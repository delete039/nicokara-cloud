from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)
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


def timeline_for(
    start_ms: int,
    end_ms: int,
    confidence: float,
    *,
    mora_end_ms: int | None = None,
    engine: str,
) -> LyricTimeline:
    mora = AlignedMora(
        reading="き",
        start_ms=start_ms,
        end_ms=mora_end_ms or end_ms,
        matched=True,
        confidence=confidence,
    )
    token = AlignedToken(
        surface="君",
        reading="きみ",
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=confidence,
        moras=[mora],
    )
    line = AlignedLine(
        surface="君の",
        reading="きみの",
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=confidence,
        tokens=[token],
    )
    return LyricTimeline(
        confidence=confidence,
        lines=[line],
        alignment_engine=engine,
        alignment_model=engine,
    )


def test_robust_dual_uses_yohane_for_a_safe_higher_confidence_local_fix() -> None:
    from app.alignment.dual import RobustDualAlignment

    class Primary:
        def align(self, lyrics, transcript, *, audio_path):
            return timeline_for(1000, 2000, 0.60, engine="fa_kara_mms")

    class Yohane:
        def align(self, lyrics, transcript, *, audio_path):
            return timeline_for(1100, 2100, 0.86, engine="fa_kara_yohane")

    result = RobustDualAlignment(primary=Primary(), secondary=Yohane()).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("song.wav"),
    )

    assert result.alignment_engine == "fa_kara_robust_dual"
    assert result.lines[0].start_ms == 1100
    assert result.lines[0].end_ms == 2100
    assert "robust_dual_mms_prior" in result.warnings


def test_robust_dual_rejects_a_large_yohane_line_shift() -> None:
    from app.alignment.dual import RobustDualAlignment

    class Primary:
        def align(self, lyrics, transcript, *, audio_path):
            return timeline_for(1000, 2000, 0.60, engine="fa_kara_mms")

    class Yohane:
        def align(self, lyrics, transcript, *, audio_path):
            return timeline_for(9000, 10000, 0.99, engine="fa_kara_yohane")

    result = RobustDualAlignment(primary=Primary(), secondary=Yohane()).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("song.wav"),
    )

    assert result.lines[0].start_ms == 1000
    assert result.lines[0].end_ms == 2000
    assert "robust_dual_rejected_candidate" in result.warnings


def test_robust_dual_falls_back_to_mms_when_yohane_fails() -> None:
    from app.alignment.dual import RobustDualAlignment

    class Primary:
        def align(self, lyrics, transcript, *, audio_path):
            return timeline_for(1000, 2000, 0.60, engine="fa_kara_mms")

    class Yohane:
        def align(self, lyrics, transcript, *, audio_path):
            raise RuntimeError("worker failed")

    result = RobustDualAlignment(primary=Primary(), secondary=Yohane()).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("song.wav"),
    )

    assert result.alignment_engine == "fa_kara_robust_dual"
    assert result.lines[0].start_ms == 1000
    assert "robust_dual_yohane_fallback" in result.warnings


def test_robust_dual_rejects_a_systematic_global_shift() -> None:
    from app.alignment.dual import RobustDualAlignment

    def with_lines(starts: list[int], engine: str) -> LyricTimeline:
        base = timeline_for(starts[0], starts[0] + 1000, 0.60, engine=engine)
        lines = [
            timeline_for(start, start + 1000, 0.60, engine=engine).lines[0]
            for start in starts
        ]
        return replace(base, lines=lines)

    primary_timeline = with_lines([1000, 3000, 5000], "fa_kara_mms")
    secondary_timeline = with_lines([4000, 6000, 8000], "fa_kara_yohane")
    secondary_timeline = replace(
        secondary_timeline,
        confidence=0.90,
        lines=[replace(line, confidence=0.90) for line in secondary_timeline.lines],
    )

    class Primary:
        def align(self, lyrics, transcript, *, audio_path):
            return primary_timeline

    class Yohane:
        def align(self, lyrics, transcript, *, audio_path):
            return secondary_timeline

    result = RobustDualAlignment(primary=Primary(), secondary=Yohane()).align(
        sample_lyrics(),
        TranscriptDocument("ja", 1.0, 1.0, "", []),
        audio_path=Path("song.wav"),
    )

    assert [line.start_ms for line in result.lines] == [1000, 3000, 5000]
    assert "robust_dual_global_guard" in result.warnings
