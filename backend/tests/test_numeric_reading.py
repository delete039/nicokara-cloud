from __future__ import annotations

import pytest

from app.lyrics.numeric_reading import integer_reading


@pytest.mark.parametrize(
    ("digits", "reading"),
    [
        ("300", "さんびゃく"),
        ("600", "ろっぴゃく"),
        ("800", "はっぴゃく"),
        ("3000", "さんぜん"),
        ("8000", "はっせん"),
        ("10000", "いちまん"),
        ("100000000", "いちおく"),
        ("1000000000000", "いっちょう"),
    ],
)
def test_integer_reading_applies_large_number_sound_changes(
    digits: str,
    reading: str,
) -> None:
    assert integer_reading(digits) == reading
