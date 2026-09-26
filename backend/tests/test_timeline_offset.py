from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
    shift_timeline,
)


def test_shift_timeline_moves_nested_timing_and_clamps_at_zero() -> None:
    timeline = LyricTimeline(
        confidence=0.9,
        lines=[
            AlignedLine(
                surface="今日",
                reading="きょう",
                start_ms=250,
                end_ms=1250,
                confidence=0.8,
                tokens=[
                    AlignedToken(
                        surface="今日",
                        reading="きょう",
                        start_ms=300,
                        end_ms=1200,
                        confidence=0.8,
                        moras=[
                            AlignedMora("きょ", 300, 700, True, 0.8),
                            AlignedMora("う", 700, 1200, True, 0.8),
                        ],
                    )
                ],
            )
        ],
        warnings=["existing"],
    )

    shifted = shift_timeline(timeline, -300)

    assert shifted.lines[0].start_ms == 0
    assert shifted.lines[0].end_ms == 950
    assert shifted.lines[0].tokens[0].start_ms == 0
    assert shifted.lines[0].tokens[0].end_ms == 900
    assert [(m.start_ms, m.end_ms) for m in shifted.lines[0].tokens[0].moras] == [
        (0, 400),
        (400, 900),
    ]
    assert shifted.warnings == ["existing", "timeline_offset_applied:-300ms"]
    assert timeline.lines[0].start_ms == 250


def test_shift_timeline_keeps_zero_length_segments_valid() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            AlignedLine("a", "a", 100, 100, 1, [
                AlignedToken("a", "a", 100, 100, 1, [
                    AlignedMora("a", 100, 100, True, 1),
                ])
            ])
        ],
    )

    shifted = shift_timeline(timeline, -300)

    assert shifted.lines[0].start_ms == 0
    assert shifted.lines[0].end_ms == 0
    assert shifted.lines[0].tokens[0].start_ms == 0
    assert shifted.lines[0].tokens[0].end_ms == 0
