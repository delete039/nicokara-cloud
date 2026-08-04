from __future__ import annotations

import importlib

import pytest

from app.alignment.models import AlignedLine, AlignedToken


def test_ruby_is_created_for_kanji_runs_not_the_whole_mixed_token() -> None:
    try:
        module = importlib.import_module("app.subtitle.ruby")
    except ModuleNotFoundError:
        pytest.fail("Ruby subtitle layout is not implemented")

    line = AlignedLine(
        surface="食べる物語",
        reading="たべるものがたり",
        start_ms=1000,
        end_ms=4000,
        confidence=1.0,
        tokens=[
            AlignedToken("食べる", "たべる", 1000, 2000, 1.0),
            AlignedToken("物語", "ものがたり", 2000, 4000, 1.0),
        ],
    )

    placements = module.ruby_placements(
        line,
        play_res_x=1920,
        baseline_y=670,
        base_font_size=96,
        center_x=960,
    )

    assert [item.text for item in placements] == ["た", "ものがたり"]
    assert [(item.x, item.y) for item in placements] == [
        (830, 620),
        (1058, 620),
    ]


def test_kana_only_tokens_never_receive_ruby() -> None:
    module = importlib.import_module("app.subtitle.ruby")
    line = AlignedLine(
        surface="かなだけ",
        reading="かなだけ",
        start_ms=0,
        end_ms=1000,
        confidence=1.0,
        tokens=[AlignedToken("かなだけ", "かなだけ", 0, 1000, 1.0)],
    )

    placements = module.ruby_placements(
        line,
        play_res_x=1920,
        baseline_y=670,
        base_font_size=96,
    )

    assert placements == []
