from __future__ import annotations

import pytest

from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)
from app.alignment.review import (
    TimelineReviewError,
    apply_timeline_review,
    lyric_timeline_from_dict,
)


def source_timeline() -> LyricTimeline:
    return LyricTimeline(
        confidence=0.8,
        lines=[
            AlignedLine(
                surface="今日",
                reading="きょう",
                start_ms=1000,
                end_ms=2000,
                confidence=0.7,
                tokens=[
                    AlignedToken(
                        surface="今日",
                        reading="きょう",
                        start_ms=1000,
                        end_ms=2000,
                        confidence=0.7,
                        moras=[
                            AlignedMora("きょ", 1000, 1500, True, 0.7),
                            AlignedMora("う", 1500, 2000, True, 0.7),
                        ],
                    )
                ],
            )
        ],
    )


def test_applies_reviewed_timing_and_rebuilds_moras() -> None:
    reviewed = apply_timeline_review(
        source_timeline(),
        {
            "lines": [
                {
                    "start_ms": 2000,
                    "end_ms": 3200,
                    "tokens": [
                        {
                            "reading": "こんにち",
                            "start_ms": 2000,
                            "end_ms": 3200,
                        }
                    ],
                }
            ]
        },
    )

    assert reviewed.lines[0].surface == "今日"
    assert reviewed.lines[0].reading == "こんにち"
    assert reviewed.lines[0].start_ms == 2000
    assert [mora.reading for mora in reviewed.lines[0].tokens[0].moras] == [
        "こ",
        "ん",
        "に",
        "ち",
    ]
    assert reviewed.lines[0].tokens[0].moras[-1].end_ms == 3200


def test_preserves_reviewed_mora_boundaries() -> None:
    reviewed = apply_timeline_review(
        source_timeline(),
        {
            "lines": [
                {
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "tokens": [
                        {
                            "reading": "きょう",
                            "start_ms": 1000,
                            "end_ms": 2000,
                            "moras": [
                                {
                                    "reading": "きょ",
                                    "start_ms": 1000,
                                    "end_ms": 1700,
                                },
                                {
                                    "reading": "う",
                                    "start_ms": 1700,
                                    "end_ms": 2000,
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )

    assert [
        (mora.reading, mora.start_ms, mora.end_ms)
        for mora in reviewed.lines[0].tokens[0].moras
    ] == [("きょ", 1000, 1700), ("う", 1700, 2000)]


def test_accepts_zero_duration_tokens_from_the_generated_timeline() -> None:
    source = source_timeline()
    source_line = source.lines[0]
    source = LyricTimeline(
        confidence=source.confidence,
        lines=[
            AlignedLine(
                surface=f"{source_line.surface}，",
                reading=f"{source_line.reading}、",
                start_ms=source_line.start_ms,
                end_ms=source_line.end_ms,
                confidence=source_line.confidence,
                tokens=[
                    *source_line.tokens,
                    AlignedToken(
                        surface="，",
                        reading="、",
                        start_ms=source_line.end_ms,
                        end_ms=source_line.end_ms,
                        confidence=1.0,
                        moras=[],
                    ),
                ],
            )
        ],
    )

    reviewed = apply_timeline_review(
        source,
        {
            "lines": [
                {
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "tokens": [
                        {
                            "reading": "きょう",
                            "start_ms": 1000,
                            "end_ms": 2000,
                        },
                        {
                            "reading": "、",
                            "start_ms": 2000,
                            "end_ms": 2000,
                        },
                    ],
                }
            ]
        },
    )

    punctuation = reviewed.lines[0].tokens[1]
    assert punctuation.start_ms == punctuation.end_ms == 2000
    assert punctuation.moras == []


def test_preserves_alignment_metadata_when_loading_and_reviewing() -> None:
    source = source_timeline()
    stored = source.to_dict()
    stored["alignment_engine"] = "fa_kara_mms"
    stored["alignment_model"] = "torchaudio.pipelines.MMS_FA"

    loaded = lyric_timeline_from_dict(stored)
    reviewed = apply_timeline_review(
        loaded,
        {
            "lines": [
                {
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "tokens": [
                        {
                            "reading": "きょう",
                            "start_ms": 1000,
                            "end_ms": 2000,
                        }
                    ],
                }
            ]
        },
    )

    assert reviewed.alignment_engine == "fa_kara_mms"
    assert reviewed.alignment_model == "torchaudio.pipelines.MMS_FA"


def test_rejects_review_with_a_different_timeline_shape() -> None:
    with pytest.raises(TimelineReviewError, match="line count"):
        apply_timeline_review(source_timeline(), {"lines": []})


def test_rejects_overlapping_reviewed_lines() -> None:
    original = source_timeline()
    original = LyricTimeline(
        confidence=original.confidence,
        lines=[original.lines[0], original.lines[0]],
    )
    with pytest.raises(TimelineReviewError, match="line 2 overlaps"):
        apply_timeline_review(
            original,
            {
                "lines": [
                    {"start_ms": 0, "end_ms": 1500, "tokens": [
                        {"reading": "きょう", "start_ms": 0, "end_ms": 1500}
                    ]},
                    {"start_ms": 1400, "end_ms": 2500, "tokens": [
                        {"reading": "きょう", "start_ms": 1400, "end_ms": 2500}
                    ]},
                ]
            },
        )
