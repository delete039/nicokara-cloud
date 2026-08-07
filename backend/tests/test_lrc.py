from __future__ import annotations

from app.alignment.models import AlignedLine, AlignedToken, LyricTimeline
from app.lyrics.lrc import parse_lrc, retime_timeline_from_lrc


def test_parse_lrc_extracts_plain_lyrics_and_line_starts() -> None:
    parsed = parse_lrc(
        "[ar:artist]\n[00:01.00]{今日|きょう}も\n[00:03:50]歌う\n"
    )

    assert parsed.lyrics_text == "今日も\n歌う"
    assert parsed.line_starts_ms == [1000, 3500]


def test_retime_timeline_uses_lrc_line_windows() -> None:
    timeline = LyricTimeline(
        confidence=0.8,
        lines=[
            AlignedLine(
                surface="今日も",
                reading="きょうも",
                start_ms=2000,
                end_ms=3000,
                confidence=0.8,
                tokens=[
                    AlignedToken(
                        surface="今日も",
                        reading="きょうも",
                        start_ms=2000,
                        end_ms=3000,
                        confidence=0.8,
                    )
                ],
            ),
            AlignedLine(
                surface="歌う",
                reading="うたう",
                start_ms=4000,
                end_ms=5000,
                confidence=0.8,
                tokens=[
                    AlignedToken(
                        surface="歌う",
                        reading="うたう",
                        start_ms=4000,
                        end_ms=5000,
                        confidence=0.8,
                    )
                ],
            ),
        ],
    )

    result = retime_timeline_from_lrc(timeline, [1000, 3500])

    assert [(line.start_ms, line.end_ms) for line in result.lines] == [
        (1000, 3500),
        (3500, 4500),
    ]
    assert "lrc_timing_applied" in result.warnings
