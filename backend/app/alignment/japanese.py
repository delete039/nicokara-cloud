from __future__ import annotations

import unicodedata

from pykakasi import kakasi


SMALL_KANA = frozenset("ゃゅょぁぃぅぇぉゎゕゖ")
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
        if character in SMALL_KANA and moras:
            moras[-1] += character
        else:
            moras.append(character)
    return moras
