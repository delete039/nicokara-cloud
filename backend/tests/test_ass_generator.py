from __future__ import annotations

import importlib
import re

import pytest

from app.alignment.models import AlignedLine, AlignedToken, LyricTimeline


def line(text: str, reading: str, start_ms: int, end_ms: int) -> AlignedLine:
    return AlignedLine(
        surface=text,
        reading=reading,
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=1.0,
        tokens=[
            AlignedToken(
                text,
                reading,
                start_ms,
                end_ms,
                1.0,
            )
        ],
    )


def timing_timeline() -> LyricTimeline:
    return LyricTimeline(
        confidence=1.0,
        lines=[
            line("第一句", "だいいちぎょう", 5000, 7000),
            line("第二句", "だいにぎょう", 8000, 10000),
            line("第三句", "だいさんぎょう", 12000, 14000),
            line("間奏後", "かんそうご", 30000, 32000),
        ],
    )


def base_event(content: str, text: str) -> str:
    return next(
        event
        for event in content.splitlines()
        if ",LyricBase," in event and event.endswith(text)
    )


def test_each_line_keeps_one_fixed_slot_for_its_entire_lifetime() -> None:
    try:
        module = importlib.import_module("app.subtitle.ass_generator")
    except ModuleNotFoundError:
        pytest.fail("ASS generator is not implemented")

    content = module.AssGenerator().generate(timing_timeline())
    first = base_event(content, "第一句")
    second = base_event(content, "第二句")
    third = base_event(content, "第三句")

    assert r"\pos(672,670)" in first
    assert r"\pos(1248,842)" in second
    assert r"\pos(672,670)" in third
    assert content.count(",LyricBase,") == 4


def test_font_size_scale_and_spacing_never_change_between_lines() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())
    events = [
        event
        for event in content.splitlines()
        if ",LyricBase," in event
    ]

    typography = [
        re.search(r"\\fs(\d+)\\fscx(\d+)\\fscy(\d+)", event).groups()
        for event in events
    ]
    assert typography == [("120", "100", "100")] * 4
    assert all(r"\fsp0" in event for event in events)


def test_both_fixed_slots_stay_in_the_lower_middle_of_1080p_frame() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())
    positions = [
        tuple(map(int, match.groups()))
        for event in content.splitlines()
        if ",LyricBase," in event
        for match in [re.search(r"\\pos\((\d+),(\d+)\)", event)]
        if match
    ]

    assert set(positions) == {(672, 670), (1248, 842)}
    assert all(560 <= y <= 860 for _, y in positions)


def test_short_vocal_gap_keeps_completed_karaoke_visible_until_next_line() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())
    first_highlight = next(
        event
        for event in content.splitlines()
        if event.startswith(
            "Dialogue: 3,0:00:05.00,0:00:08.00,Highlight"
        )
    )

    assert r"{\k" in first_highlight


def test_long_interlude_hides_old_subtitles_and_previews_new_section() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())

    assert base_event(content, "第三句").startswith(
        "Dialogue: 1,0:00:08.00,0:00:14.00,LyricBase"
    )
    assert base_event(content, "間奏後").startswith(
        "Dialogue: 1,0:00:27.00,0:00:32.00,LyricBase"
    )


def test_first_song_line_is_visible_three_seconds_before_singing() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())

    assert base_event(content, "第一句").startswith(
        "Dialogue: 1,0:00:02.00,0:00:08.00,LyricBase"
    )
    assert base_event(content, "第二句").startswith(
        "Dialogue: 1,0:00:05.00,0:00:12.00,LyricBase"
    )


def test_base_highlight_glow_and_ruby_styles_are_preserved() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    content = module.AssGenerator().generate(timing_timeline())

    assert "Style: LyricBase,Noto Sans CJK JP,120," in content
    assert "&H00000000,&H00000000,&H00FFFFFF" in content
    assert "Style: Highlight,Noto Sans CJK JP,120,&H000000FF" in content
    assert ",Ruby," in content
    assert ",Glow," in content
    assert r"\blur8" in content


def test_user_text_is_escaped_in_every_visual_layer() -> None:
    module = importlib.import_module("app.subtitle.ass_generator")
    timeline = LyricTimeline(
        confidence=1.0,
        lines=[line(r"{\N}", r"{\N}", 3000, 4000)],
    )

    content = module.AssGenerator().generate(timeline)

    assert r"\{\\N\}" in content
