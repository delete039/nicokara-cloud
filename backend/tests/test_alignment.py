from __future__ import annotations

import importlib

import pytest

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.lyrics.models import LyricDocument, LyricLine, LyricToken


def exact_lyrics() -> LyricDocument:
    return LyricDocument(
        provider="deepseek",
        source_text="物語\nいつも",
        lines=[
            LyricLine(
                source="物語",
                surface="物語",
                reading="ものがたり",
                tokens=[LyricToken(surface="物語", reading="ものがたり")],
            ),
            LyricLine(
                source="いつも",
                surface="いつも",
                reading="いつも",
                tokens=[LyricToken(surface="いつも", reading="いつも")],
            ),
        ],
    )


def exact_transcript() -> TranscriptDocument:
    return TranscriptDocument(
        language="ja",
        language_probability=0.99,
        duration_seconds=5.0,
        text="物語いつも",
        segments=[
            TranscriptSegment(
                id=0,
                text="物語いつも",
                start_ms=1000,
                end_ms=4200,
                confidence=-0.1,
                no_speech_probability=0.01,
                words=[
                    TranscriptWord(
                        text="物語",
                        start_ms=1000,
                        end_ms=3000,
                        confidence=0.95,
                    ),
                    TranscriptWord(
                        text="いつも",
                        start_ms=3300,
                        end_ms=4200,
                        confidence=0.96,
                    ),
                ],
            )
        ],
    )


def test_exact_mora_match_preserves_whisper_word_boundaries() -> None:
    try:
        aligner_module = importlib.import_module("app.alignment.aligner")
    except ModuleNotFoundError:
        pytest.fail("Lyric timeline aligner is not implemented")

    timeline = aligner_module.LyricTimelineAligner().align(
        exact_lyrics(),
        exact_transcript(),
    )

    assert timeline.confidence == pytest.approx(1.0)
    assert timeline.warnings == []
    assert len(timeline.lines) == 2
    assert (timeline.lines[0].start_ms, timeline.lines[0].end_ms) == (1000, 3000)
    assert (timeline.lines[1].start_ms, timeline.lines[1].end_ms) == (3300, 4200)
    assert (timeline.lines[0].tokens[0].start_ms, timeline.lines[0].tokens[0].end_ms) == (
        1000,
        3000,
    )
    assert [mora.reading for mora in timeline.lines[0].tokens[0].moras] == [
        "も",
        "の",
        "が",
        "た",
        "り",
    ]
    assert all(mora.matched for mora in timeline.lines[0].tokens[0].moras)


def test_missing_asr_mora_is_interpolated_between_matches() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="君の物語",
        lines=[
            LyricLine(
                source="君の物語",
                surface="君の物語",
                reading="きみのものがたり",
                tokens=[
                    LyricToken(surface="君", reading="きみ"),
                    LyricToken(surface="の", reading="の"),
                    LyricToken(surface="物語", reading="ものがたり"),
                ],
            )
        ],
    )
    transcript = TranscriptDocument(
        language="ja",
        language_probability=0.98,
        duration_seconds=4.0,
        text="きみものがたり",
        segments=[
            TranscriptSegment(
                id=0,
                text="きみものがたり",
                start_ms=1000,
                end_ms=3500,
                confidence=-0.2,
                no_speech_probability=0.01,
                words=[
                    TranscriptWord(
                        text="きみ",
                        start_ms=1000,
                        end_ms=1600,
                        confidence=0.95,
                    ),
                    TranscriptWord(
                        text="ものがたり",
                        start_ms=2000,
                        end_ms=3500,
                        confidence=0.94,
                    ),
                ],
            )
        ],
    )

    timeline = aligner_module.LyricTimelineAligner().align(lyrics, transcript)

    interpolated = timeline.lines[0].tokens[1].moras[0]
    assert interpolated.reading == "の"
    assert interpolated.matched is False
    assert (interpolated.start_ms, interpolated.end_ms) == (1600, 2000)
    assert 0 < timeline.confidence < 1
    assert timeline.warnings == ["partial_alignment"]
    all_moras = [
        mora
        for token in timeline.lines[0].tokens
        for mora in token.moras
    ]
    assert all(
        previous.end_ms <= current.start_ms
        for previous, current in zip(all_moras, all_moras[1:])
    )


def test_unmatched_leading_lines_are_backfilled_before_first_audio_match() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="かき\nくけこ\nあいう",
        lines=[
            LyricLine(
                source="かき",
                surface="かき",
                reading="かき",
                tokens=[LyricToken(surface="かき", reading="かき")],
            ),
            LyricLine(
                source="くけこ",
                surface="くけこ",
                reading="くけこ",
                tokens=[LyricToken(surface="くけこ", reading="くけこ")],
            ),
            LyricLine(
                source="あいう",
                surface="あいう",
                reading="あいう",
                tokens=[LyricToken(surface="あいう", reading="あいう")],
            ),
        ],
    )
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=6.0,
        text="あいう",
        segments=[
            TranscriptSegment(
                id=0,
                text="あいう",
                start_ms=5000,
                end_ms=5600,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("あいう", 5000, 5600, 1.0)],
            )
        ],
    )

    timeline = aligner_module.LyricTimelineAligner().align(lyrics, transcript)

    assert (timeline.lines[0].start_ms, timeline.lines[0].end_ms) == (4000, 4400)
    assert (timeline.lines[1].start_ms, timeline.lines[1].end_ms) == (4400, 5000)
    assert (timeline.lines[2].start_ms, timeline.lines[2].end_ms) == (5000, 5600)
    leading_moras = [
        mora
        for line in timeline.lines[:2]
        for token in line.tokens
        for mora in token.moras
    ]
    assert all(mora.end_ms > mora.start_ms for mora in leading_moras)
    assert all(not mora.matched for mora in leading_moras)
    assert timeline.warnings == ["partial_alignment"]


def test_punctuation_only_token_moves_to_the_next_mora_boundary() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="きみ、もの",
        lines=[
            LyricLine(
                source="きみ、もの",
                surface="きみ、もの",
                reading="きみ、もの",
                tokens=[
                    LyricToken(surface="きみ", reading="きみ"),
                    LyricToken(surface="、", reading="、"),
                    LyricToken(surface="もの", reading="もの"),
                ],
            )
        ],
    )
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=3.0,
        text="きみもの",
        segments=[
            TranscriptSegment(
                id=0,
                text="きみもの",
                start_ms=500,
                end_ms=2500,
                confidence=-0.1,
                no_speech_probability=0,
                words=[
                    TranscriptWord("きみ", 500, 1200, 1.0),
                    TranscriptWord("もの", 1500, 2500, 1.0),
                ],
            )
        ],
    )

    timeline = aligner_module.LyricTimelineAligner().align(lyrics, transcript)

    punctuation = timeline.lines[0].tokens[1]
    assert punctuation.moras == []
    assert (punctuation.start_ms, punctuation.end_ms) == (1500, 1500)
    assert timeline.confidence == 1.0


def test_empty_asr_is_rejected_instead_of_spreading_lyrics_over_song() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=220.0,
        text="",
        segments=[],
    )

    with pytest.raises(
        aligner_module.AlignmentQualityError,
        match="No ASR word timestamps",
    ):
        aligner_module.LyricTimelineAligner().align(
            exact_lyrics(),
            transcript,
        )


def test_repeated_lyrics_prefer_nearby_partial_audio_over_distant_exact_match() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="まえ\nあいう",
        lines=[
            LyricLine(
                source="まえ",
                surface="まえ",
                reading="まえ",
                tokens=[LyricToken("まえ", "まえ")],
            ),
            LyricLine(
                source="あいう",
                surface="あいう",
                reading="あいう",
                tokens=[LyricToken("あいう", "あいう")],
            ),
        ],
    )
    filler_times = list(range(5000, 90000, 5000))
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=110.0,
        text="まえあいえ" + "ら" * len(filler_times) + "あいう",
        segments=[
            TranscriptSegment(
                id=0,
                text="まえ",
                start_ms=1000,
                end_ms=1500,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("まえ", 1000, 1500, 1.0)],
            ),
            TranscriptSegment(
                id=1,
                text="あいえ",
                start_ms=2000,
                end_ms=3000,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("あいえ", 2000, 3000, 0.8)],
            ),
            *[
                TranscriptSegment(
                    id=index + 2,
                    text="ら",
                    start_ms=time,
                    end_ms=time + 300,
                    confidence=-0.5,
                    no_speech_probability=0,
                    words=[TranscriptWord("ら", time, time + 300, 0.7)],
                )
                for index, time in enumerate(filler_times)
            ],
            TranscriptSegment(
                id=99,
                text="あいう",
                start_ms=100000,
                end_ms=101000,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("あいう", 100000, 101000, 1.0)],
            ),
        ],
    )

    timeline = aligner_module.LyricTimelineAligner().align(lyrics, transcript)

    assert timeline.lines[0].start_ms == 1000
    assert timeline.lines[1].start_ms < 5000
    assert timeline.lines[1].end_ms <= 5000


def test_unrelated_asr_is_rejected_instead_of_fabricating_a_timeline() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="あいうえお\nかきくけこ",
        lines=[
            LyricLine(
                source=reading,
                surface=reading,
                reading=reading,
                tokens=[LyricToken(reading, reading)],
            )
            for reading in ("あいうえお", "かきくけこ")
        ],
    )
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=8.0,
        text="あxyz",
        segments=[
            TranscriptSegment(
                id=0,
                text="あxyz",
                start_ms=1000,
                end_ms=3000,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("あxyz", 1000, 3000, 1.0)],
            )
        ],
    )

    with pytest.raises(
        aligner_module.AlignmentQualityError,
        match="insufficient",
    ):
        aligner_module.LyricTimelineAligner().align(
            lyrics,
            transcript,
        )


def test_overlapping_whisper_segments_do_not_create_overlapping_lyric_lines() -> None:
    aligner_module = importlib.import_module("app.alignment.aligner")
    lyrics = LyricDocument(
        provider="local",
        source_text="あ\nい",
        lines=[
            LyricLine(
                source=reading,
                surface=reading,
                reading=reading,
                tokens=[LyricToken(reading, reading)],
            )
            for reading in ("あ", "い")
        ],
    )
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=3.0,
        text="あい",
        segments=[
            TranscriptSegment(
                id=0,
                text="あ",
                start_ms=1000,
                end_ms=2000,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("あ", 1000, 2000, 1.0)],
            ),
            TranscriptSegment(
                id=1,
                text="い",
                start_ms=1900,
                end_ms=2500,
                confidence=-0.1,
                no_speech_probability=0,
                words=[TranscriptWord("い", 1900, 2500, 1.0)],
            ),
        ],
    )

    timeline = aligner_module.LyricTimelineAligner().align(lyrics, transcript)

    assert timeline.lines[0].end_ms <= timeline.lines[1].start_ms
