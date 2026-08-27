from __future__ import annotations

import unicodedata

from pykakasi import kakasi


# FA-Kara's default sylla_split keeps small kana, a trailing sokuon, and a
# prolonged-sound mark in the preceding pronunciation unit.  The model then
# receives the same boundaries that Kirakara uses for its lyric timestamps.
COMBINING_KANA = frozenset(
    "ゃゅょぁぃぅぇぉゎゕゖっー"
    "ャュョァィゥェォヮヵヶッ"
)
_CONVERTER = kakasi()


def normalize_reading(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    hiragana = "".join(item["hira"] for item in _CONVERTER.convert(normalized))
    return "".join(
        character.lower()
        for character in hiragana
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "S"))
    )


def split_moras(reading: str) -> list[str]:
    moras: list[str] = []
    for character in reading:
        category = unicodedata.category(character)
        if character.isspace() or category.startswith("P"):
            continue
        if character in COMBINING_KANA and moras:
            moras[-1] += character
        else:
            moras.append(character)
    return moras


def split_kana_units(text: str) -> list[str]:
    """Split visible kana with the same boundaries as FA-Kara sylla_split."""
    units: list[str] = []
    for character in text:
        if character in COMBINING_KANA and units:
            units[-1] += character
        else:
            units.append(character)
    return units
