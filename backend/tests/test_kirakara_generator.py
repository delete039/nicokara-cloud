from __future__ import annotations

from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)
from app.subtitle.kirakara_generator import KirakaraAssConfig, KirakaraAssGenerator


def lyric_line(
    surface: str,
    reading: str,
    start_ms: int,
    end_ms: int,
    tokens: list[AlignedToken],
) -> AlignedLine:
    return AlignedLine(
        surface=surface,
        reading=reading,
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=1,
        tokens=tokens,
    )


def test_kirakara_generator_uses_alternating_upper_left_and_lower_right_slots() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "今日も",
                "きょうも",
                5000,
                7000,
                [
                    AlignedToken(
                        "今日",
                        "きょう",
                        5000,
                        6500,
                        1,
                        [
                            AlignedMora("きょ", 5000, 5750, True, 1),
                            AlignedMora("う", 5750, 6500, True, 1),
                        ],
                    ),
                    AlignedToken("も", "も", 6500, 7000, 1),
                ],
            ),
            lyric_line(
                "歌う",
                "うたう",
                8000,
                10000,
                [
                    AlignedToken("歌", "うた", 8000, 9500, 1),
                    AlignedToken("う", "う", 9500, 10000, 1),
                ],
            ),
            lyric_line(
                "明日へ",
                "あしたへ",
                12000,
                14000,
                [
                    AlignedToken("明日", "あした", 12000, 13500, 1),
                    AlignedToken("へ", "へ", 13500, 14000, 1),
                ],
            ),
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)

    upper_events = [
        event
        for event in content.splitlines()
        if ",KirakaraBase," in event and r"\an4\pos(192,645)" in event
    ]
    lower_events = [
        event
        for event in content.splitlines()
        if ",KirakaraBase," in event and r"\an6\pos(1728,845)" in event
    ]
    assert len(upper_events) == 2
    assert len(lower_events) == 1
    assert upper_events[0].startswith("Dialogue: 1,0:00:02.00,0:00:08.00")
    assert lower_events[0].startswith("Dialogue: 1,0:00:05.00,0:00:10.00")
    assert upper_events[1].startswith("Dialogue: 1,0:00:08.00,0:00:14.00")


def test_kirakara_generator_places_ruby_only_over_kanji_groups() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "今日も",
                "きょうも",
                1000,
                2500,
                [
                    AlignedToken("今日", "きょう", 1000, 2000, 1),
                    AlignedToken("も", "も", 2000, 2500, 1),
                ],
            )
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    ruby_events = [
        event for event in content.splitlines() if ",KirakaraRuby," in event
    ]

    assert len(ruby_events) == 1
    assert ruby_events[0].endswith("きょう")
    assert "きょうも" not in content


def test_kirakara_generator_keeps_mora_driven_karaoke_progress() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "今日",
                "きょう",
                1000,
                2000,
                [
                    AlignedToken(
                        "今日",
                        "きょう",
                        1000,
                        2000,
                        1,
                        [
                            AlignedMora("きょ", 1000, 1500, True, 1),
                            AlignedMora("う", 1500, 2000, True, 1),
                        ],
                    )
                ],
            )
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)

    assert r"{\kf50}今{\kf50}日" in content


def test_kirakara_generator_maps_browser_style_to_ass_coordinates_and_colors() -> None:
    config = KirakaraAssConfig.from_browser_style(
        {
            "font_family": "Yu Gothic",
            "font_size": 72,
            "ruby_size": 30,
            "stroke_width": 6,
            "upper_y": 410,
            "lower_y": 580,
            "color_before": "#fefefe",
            "color_after": "#123456",
        }
    )

    assert config.font_name == "Yu Gothic"
    assert config.base_font_size == 108
    assert config.ruby_font_size == 45
    assert config.upper_y == 615
    assert config.lower_y == 870
    assert config.unsung_color == "&H00FEFEFE"
    assert config.sung_color == "&H00563412"
