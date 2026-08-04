from __future__ import annotations

import importlib

import pytest

from app.alignment.models import AlignedLine, AlignedMora, AlignedToken


def test_token_is_split_into_character_level_karaoke_chunks() -> None:
    try:
        effect_module = importlib.import_module("app.subtitle.karaoke_effect")
    except ModuleNotFoundError:
        pytest.fail("Karaoke effect generator is not implemented")

    token = AlignedToken(
        surface="君の",
        reading="きみの",
        start_ms=1000,
        end_ms=2000,
        confidence=1.0,
        moras=[
            AlignedMora("き", 1000, 1333, True, 1.0),
            AlignedMora("み", 1333, 1666, True, 1.0),
            AlignedMora("の", 1666, 2000, True, 1.0),
        ],
    )

    chunks = effect_module.character_chunks(token)

    assert [chunk.text for chunk in chunks] == ["君", "の"]
    assert [chunk.duration_cs for chunk in chunks] == [50, 50]
    assert sum(chunk.duration_cs for chunk in chunks) == 100
    assert effect_module.render_karaoke(chunks) == r"{\kf50}君{\kf50}の"


def test_line_chunks_cover_gaps_between_tokens() -> None:
    effect_module = importlib.import_module("app.subtitle.karaoke_effect")
    line = AlignedLine(
        surface="君の",
        reading="きみの",
        start_ms=1000,
        end_ms=2500,
        confidence=1.0,
        tokens=[
            AlignedToken("君", "きみ", 1000, 1800, 1.0),
            AlignedToken("の", "の", 2000, 2500, 1.0),
        ],
    )

    chunks = effect_module.line_chunks(line)

    assert [(chunk.text, chunk.duration_cs) for chunk in chunks] == [
        ("君", 100),
        ("の", 50),
    ]
    assert sum(chunk.duration_cs for chunk in chunks) == 150


def test_character_chunks_preserve_audio_derived_mora_durations() -> None:
    effect_module = importlib.import_module("app.subtitle.karaoke_effect")
    token = AlignedToken(
        surface="かな",
        reading="かな",
        start_ms=1000,
        end_ms=2000,
        confidence=1.0,
        moras=[
            AlignedMora("か", 1000, 1200, True, 1.0),
            AlignedMora("な", 1200, 2000, True, 1.0),
        ],
    )

    chunks = effect_module.character_chunks(token)

    assert [(chunk.text, chunk.duration_cs) for chunk in chunks] == [
        ("か", 20),
        ("な", 80),
    ]


def test_user_text_is_escaped_before_ass_rendering() -> None:
    effect_module = importlib.import_module("app.subtitle.karaoke_effect")

    rendered = effect_module.render_karaoke(
        [effect_module.KaraokeChunk(text=r"{\N}", duration_cs=25)]
    )

    assert rendered == r"{\kf25}\{\\N\}"


def test_k_tags_never_assign_negative_time_to_punctuation() -> None:
    effect_module = importlib.import_module("app.subtitle.karaoke_effect")
    line = AlignedLine(
        surface="あい，",
        reading="あい、",
        start_ms=0,
        end_ms=30,
        confidence=1.0,
        tokens=[
            AlignedToken("あ", "あ", 0, 15, 1.0),
            AlignedToken("い", "い", 15, 30, 1.0),
            AlignedToken("，", "、", 30, 30, 1.0),
        ],
    )

    chunks = effect_module.line_chunks(line)
    rendered = effect_module.render_karaoke(chunks)

    assert [(chunk.text, chunk.duration_cs) for chunk in chunks] == [
        ("あ", 2),
        ("い", 1),
        ("，", 0),
    ]
    assert rendered == r"{\kf2}あ{\kf1}い，"
