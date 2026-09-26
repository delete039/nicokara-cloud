from __future__ import annotations

import importlib

import pytest


def test_split_moras_keeps_combined_kana_and_timing_marks() -> None:
    try:
        japanese_module = importlib.import_module("app.alignment.japanese")
    except ModuleNotFoundError:
        pytest.fail("Japanese alignment helpers are not implemented")

    # Match FA-Kara's default sylla_split behavior: a trailing sokuon and
    # prolonged-sound mark belong to the preceding pronunciation unit.
    assert japanese_module.split_moras("きゃっと") == ["きゃっ", "と"]
    assert japanese_module.split_moras("すーぱー") == ["すー", "ぱー"]
    assert japanese_module.split_moras("もの、がたり！") == [
        "も",
        "の",
        "が",
        "た",
        "り",
    ]


def test_normalize_reading_converts_kanji_katakana_and_punctuation() -> None:
    japanese_module = importlib.import_module("app.alignment.japanese")
    if not hasattr(japanese_module, "normalize_reading"):
        pytest.fail("Japanese reading normalization is not implemented")

    assert japanese_module.normalize_reading("物語、ストーリー！") == (
        "ものがたりすとーりー"
    )
    assert japanese_module.normalize_reading("♪物語★") == "ものがたり"


def test_split_moras_ignores_unicode_symbols_and_brackets() -> None:
    japanese_module = importlib.import_module("app.alignment.japanese")

    assert japanese_module.split_moras(
        "\u266a\u300cかな\u300d\u2605\uff08\uff09()[]{}…！？、。—+-*/=_#%&@\U0001f642"
    ) == [
        "か",
        "な",
    ]
