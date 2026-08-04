from __future__ import annotations

import importlib

import pytest


def test_split_moras_keeps_combined_kana_and_timing_marks() -> None:
    try:
        japanese_module = importlib.import_module("app.alignment.japanese")
    except ModuleNotFoundError:
        pytest.fail("Japanese alignment helpers are not implemented")

    assert japanese_module.split_moras("きゃっと") == ["きゃ", "っ", "と"]
    assert japanese_module.split_moras("すーぱー") == ["す", "ー", "ぱ", "ー"]
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
