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

    base_events = [
        event for event in content.splitlines() if ",KirakaraBase," in event
    ]
    assert any(
        event.startswith("Dialogue: 1,0:00:00.83,0:00:08.00")
        and r",645)" in event
        and event.endswith("今")
        for event in base_events
    )
    assert any(
        event.startswith("Dialogue: 1,0:00:00.83,0:00:12.00")
        and r",845)" in event
        and event.endswith("歌")
        for event in base_events
    )
    assert any(
        event.startswith("Dialogue: 1,0:00:08.00,0:00:16.00")
        and r",645)" in event
        and event.endswith("明")
        for event in base_events
    )


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

    assert len(ruby_events) == 3
    assert "".join(event[-1] for event in ruby_events) == "きょう"
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

    progress_events = [
        line for line in content.splitlines() if ",KirakaraProgress," in line
    ]
    assert progress_events[0].startswith("Dialogue: 3,0:00:01.00,0:00:01.50")
    assert r"\t(0,500,\clip(" in progress_events[0]
    assert progress_events[0].endswith("今")
    assert progress_events[1].startswith("Dialogue: 3,0:00:01.50,0:00:02.00")
    assert r"\t(0,500,\clip(" in progress_events[1]
    assert progress_events[1].endswith("日")


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


def test_kirakara_generator_keeps_a_safe_browser_font_name() -> None:
    config = KirakaraAssConfig.from_browser_style({"font_family": "'Yu Mincho'"})

    assert config.font_name == "Yu Mincho"


def test_kirakara_generator_rejects_unsafe_ass_font_names() -> None:
    config = KirakaraAssConfig.from_browser_style(
        {"font_family": "Noto Sans JP,Injected\nStyle"}
    )

    assert config.font_name == KirakaraAssConfig.font_name


def test_kirakara_generator_changes_color_one_character_at_a_time() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "春風",
                "はるかぜ",
                1000,
                3000,
                [
                    AlignedToken("春", "はる", 1000, 2000, 1),
                    AlignedToken("風", "かぜ", 2000, 3000, 1),
                ],
            )
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    progress_events = [
        line for line in content.splitlines() if ",KirakaraProgress," in line
    ]

    assert len(progress_events) == 2
    assert progress_events[0].startswith("Dialogue: 3,0:00:01.00,")
    assert r"\t(0,1000,\clip(" in progress_events[0]
    assert progress_events[0].endswith("春")
    assert progress_events[1].startswith("Dialogue: 3,0:00:02.00,")
    assert r"\t(0,1000,\clip(" in progress_events[1]
    assert progress_events[1].endswith("風")
    progress_style = next(
        line for line in content.splitlines() if line.startswith("Style: KirakaraProgress,")
    )
    sung_style = next(
        line for line in content.splitlines() if line.startswith("Style: KirakaraSung,")
    )
    assert "&H00FFFFFF" in progress_style
    assert "&H00FFFFFF" in sung_style


def test_kirakara_generator_clips_sung_fill_and_outline_continuously() -> None:
    """Kirakara clips the complete sung layer, including its white outline."""
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "春",
                "はる",
                1000,
                2000,
                [AlignedToken("春", "はる", 1000, 2000, 1)],
            )
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    progress_event = next(
        line for line in content.splitlines() if ",KirakaraProgress," in line
    )
    progress_style = next(
        line for line in content.splitlines() if line.startswith("Style: KirakaraProgress,")
    )

    assert r"\clip(" in progress_event
    assert r"\t(0,1000,\clip(" in progress_event
    assert r"\kf" not in progress_event
    assert "&H00FFFFFF" in progress_style
    assert ",1,8,0,7," in progress_style


def test_kirakara_generator_isolates_wide_ruby_and_shifts_following_text(
    monkeypatch,
) -> None:
    def fixed_text_measurer(_font_name: str, size: int, *, bold: bool = False):
        del bold
        return lambda text: float(len(text) * size)

    monkeypatch.setattr(
        "app.subtitle.kirakara_generator.text_measurer",
        fixed_text_measurer,
    )
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            lyric_line(
                "生き",
                "なまものき",
                1000,
                3000,
                [
                    AlignedToken("生", "なまもの", 1000, 2500, 1),
                    AlignedToken("き", "き", 2500, 3000, 1),
                ],
            )
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    base_events = [
        line for line in content.splitlines() if ",KirakaraBase," in line
    ]
    ruby_events = [
        line for line in content.splitlines() if ",KirakaraRuby," in line
    ]

    # Upstream Kirakara isolates a ruby group to max(base width, ruby width).
    # 4 * 39 + 3 * 8 = 180, so the 96 px base glyph is centered in that
    # group and the following glyph starts after 180 + 14 px.
    assert len(base_events) == 2
    assert r"\pos(234,645)" in base_events[0]
    assert base_events[0].endswith("生")
    assert r"\pos(386,645)" in base_events[1]
    assert base_events[1].endswith("き")
    assert len(ruby_events) == 4
    assert r"\pos(192,600)" in ruby_events[0]
    assert r"\pos(333,600)" in ruby_events[-1]


def test_kirakara_generator_preserves_mora_timing_when_counts_differ() -> None:
    token = AlignedToken(
        "\u6771\u4eac",
        "\u3068\u3046\u304d\u3087\u3046",
        1000,
        1700,
        1,
        [
            AlignedMora("\u3068", 1000, 1100, True, 1),
            AlignedMora("\u3046", 1100, 1400, True, 1),
            AlignedMora("\u304d\u3087\u3046", 1400, 1700, True, 1),
        ],
    )
    timeline = LyricTimeline(
        confidence=1,
        lines=[lyric_line(token.surface, token.reading, 1000, 1700, [token])],
    )

    content = KirakaraAssGenerator().generate(timeline)

    progress_events = [
        line for line in content.splitlines() if ",KirakaraProgress," in line
    ]
    assert r"\t(0,250,\clip(" in progress_events[0]
    assert progress_events[0].endswith("\u6771")
    assert r"\t(0,450,\clip(" in progress_events[1]
    assert progress_events[1].endswith("\u4eac")


def test_kirakara_generator_animates_ruby_with_mora_timing() -> None:
    token = AlignedToken(
        "\u4eca\u65e5",
        "\u304d\u3087\u3046",
        1000,
        2000,
        1,
        [
            AlignedMora("\u304d\u3087", 1000, 1300, True, 1),
            AlignedMora("\u3046", 1300, 2000, True, 1),
        ],
    )
    timeline = LyricTimeline(
        confidence=1,
        lines=[lyric_line(token.surface, token.reading, 1000, 2000, [token])],
    )

    content = KirakaraAssGenerator().generate(timeline)
    progress_events = [
        line for line in content.splitlines() if ",KirakaraRubyProgress," in line
    ]

    assert len(progress_events) == 3
    assert r"\t(0,150,\clip(" in progress_events[0]
    assert progress_events[0].endswith("\u304d")
    assert r"\t(0,150,\clip(" in progress_events[1]
    assert progress_events[1].endswith("\u3087")
    assert r"\t(0,700,\clip(" in progress_events[2]
    assert progress_events[2].endswith("\u3046")


def test_kirakara_ruby_progress_starts_at_the_kanji_reading_inside_a_token() -> None:
    token = AlignedToken(
        "\u304a\u9858\u3044",
        "\u304a\u306d\u304c\u3044",
        1000,
        1400,
        1,
        [
            AlignedMora("\u304a", 1000, 1100, True, 1),
            AlignedMora("\u306d", 1100, 1200, True, 1),
            AlignedMora("\u304c", 1200, 1300, True, 1),
            AlignedMora("\u3044", 1300, 1400, True, 1),
        ],
    )
    timeline = LyricTimeline(
        confidence=1,
        lines=[lyric_line(token.surface, token.reading, 1000, 1400, [token])],
    )

    content = KirakaraAssGenerator().generate(timeline)
    progress_events = [
        line for line in content.splitlines() if ",KirakaraRubyProgress," in line
    ]

    assert progress_events[0].startswith("Dialogue: 4,0:00:01.10,")
    assert r"\t(0,100,\clip(" in progress_events[0]
    assert progress_events[0].endswith("\u306d")
    assert progress_events[1].startswith("Dialogue: 4,0:00:01.20,")
    assert r"\t(0,100,\clip(" in progress_events[1]
    assert progress_events[1].endswith("\u304c")


def _plain_line(surface: str, start_ms: int, end_ms: int) -> AlignedLine:
    return lyric_line(
        surface,
        surface,
        start_ms,
        end_ms,
        [AlignedToken(surface, surface, start_ms, end_ms, 1)],
    )


def test_kirakara_generator_uses_paragraph_relative_slots_and_lifecycle() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            _plain_line("A", 10_000, 12_000),
            _plain_line("B", 13_000, 15_000),
            _plain_line("C", 17_000, 19_000),
            _plain_line("D", 30_000, 32_000),
            _plain_line("E", 33_000, 35_000),
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    base_events = [
        event for event in content.splitlines() if ",KirakaraBase," in event
    ]
    by_character = {event[-1]: event for event in base_events}

    # Upstream: 666 ms fade + 500 ms pause + 3 s indicator, then 2 s exit hold.
    assert by_character["A"].startswith("Dialogue: 1,0:00:05.83,0:00:13.00")
    assert r",645)" in by_character["A"]
    assert r"\fad(666,0)" in by_character["A"]
    assert by_character["B"].startswith("Dialogue: 1,0:00:05.83,0:00:17.00")
    assert r",845)" in by_character["B"]
    assert r"\fad(666,0)" in by_character["B"]
    assert by_character["C"].startswith("Dialogue: 1,0:00:13.00,0:00:21.00")
    assert r"\fad(0,666)" in by_character["C"]

    # A new paragraph resets to the upper slot, independent of global line index.
    assert by_character["D"].startswith("Dialogue: 1,0:00:25.83,0:00:34.00")
    assert r",645)" in by_character["D"]
    assert r"\fad(666,0)" in by_character["D"]
    assert by_character["E"].startswith("Dialogue: 1,0:00:25.83,0:00:37.00")
    assert r",845)" in by_character["E"]
    assert r"\fad(666,666)" in by_character["E"]


def test_kirakara_generator_adds_one_four_dot_indicator_per_paragraph() -> None:
    timeline = LyricTimeline(
        confidence=1,
        lines=[
            _plain_line("A", 10_000, 12_000),
            _plain_line("B", 13_000, 15_000),
            _plain_line("C", 30_000, 32_000),
        ],
    )

    content = KirakaraAssGenerator().generate(timeline)
    indicators = [
        event for event in content.splitlines() if ",KirakaraIndicator," in event
    ]

    assert len(indicators) == 8
    assert sum(event.startswith("Dialogue: 0,0:00:05.83,") for event in indicators) == 4
    assert sum(event.startswith("Dialogue: 0,0:00:25.83,") for event in indicators) == 4
    assert any(",0:00:07.00,KirakaraIndicator," in event for event in indicators)
    assert any(",0:00:09.25,KirakaraIndicator," in event for event in indicators)
    assert "Style: KirakaraIndicator," in content
