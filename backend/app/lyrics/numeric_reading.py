from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence


_ASCII_DIGITS = re.compile(r"[0-9]+")
_DIGIT_READINGS = (
    "ぜろ",
    "いち",
    "に",
    "さん",
    "よん",
    "ご",
    "ろく",
    "なな",
    "はち",
    "きゅう",
)
_LARGE_UNITS = ("", "まん", "おく", "ちょう")
_COUNTERS = frozenset(("人", "分", "泊", "つ", "丁目", "月", "日", "時", "時半"))
_JAPANESE_TEXT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


@dataclass(frozen=True)
class NumericReadingPart:
    surface: str
    reading: str


@dataclass(frozen=True)
class NumericReadingSpan:
    consumed_items: int
    parts: tuple[NumericReadingPart, ...]


def _four_digit_reading(value: int) -> str:
    if not 0 <= value <= 9999:
        raise ValueError("four digit group is out of range")
    if value == 0:
        return ""

    thousands, remainder = divmod(value, 1000)
    hundreds, remainder = divmod(remainder, 100)
    tens, ones = divmod(remainder, 10)
    parts: list[str] = []

    if thousands:
        parts.append(
            {1: "せん", 3: "さんぜん", 8: "はっせん"}.get(
                thousands,
                _DIGIT_READINGS[thousands] + "せん",
            )
        )
    if hundreds:
        parts.append(
            {
                1: "ひゃく",
                3: "さんびゃく",
                6: "ろっぴゃく",
                8: "はっぴゃく",
            }.get(hundreds, _DIGIT_READINGS[hundreds] + "ひゃく")
        )
    if tens:
        parts.append("じゅう" if tens == 1 else _DIGIT_READINGS[tens] + "じゅう")
    if ones:
        parts.append(_DIGIT_READINGS[ones])
    return "".join(parts)


def integer_reading(digits: str) -> str:
    if _ASCII_DIGITS.fullmatch(digits) is None:
        raise ValueError("integer reading requires ASCII digits")
    normalized = digits.lstrip("0") or "0"
    if normalized == "0":
        return "ぜろ"
    if len(normalized) > 16:
        raise ValueError("integer reading supports values below 10^16")

    groups: list[int] = []
    while normalized:
        groups.append(int(normalized[-4:]))
        normalized = normalized[:-4]

    parts: list[str] = []
    for group_index in range(len(groups) - 1, -1, -1):
        value = groups[group_index]
        if value == 0:
            continue
        group_reading = _four_digit_reading(value)
        unit = _LARGE_UNITS[group_index]
        if unit == "ちょう" and group_reading.endswith("いち"):
            group_reading = group_reading[:-2] + "いっ"
        parts.append(group_reading)
        parts.append(unit)
    return "".join(parts)


def _replace_ending(reading: str, old: str, new: str) -> str:
    if not reading.endswith(old):
        return reading + new
    return reading[: -len(old)] + new


def _minute_parts(digits: str) -> tuple[str, str]:
    value = int(digits)
    base = integer_reading(digits)
    last = value % 10
    if base.endswith("ひゃく") or base.endswith("びゃく") or base.endswith("ぴゃく"):
        return base[:-1] + "っ", "ぷん"
    if last == 1:
        return _replace_ending(base, "いち", "いっ"), "ぷん"
    if last == 6:
        return _replace_ending(base, "ろく", "ろっ"), "ぷん"
    if last == 8:
        return _replace_ending(base, "はち", "はっ"), "ぷん"
    if last == 0 and base.endswith("じゅう"):
        return base[:-1] + "っ", "ぷん"
    return base, "ぷん" if last in {3, 4} else "ふん"


def _night_parts(digits: str) -> tuple[str, str]:
    value = int(digits)
    base = integer_reading(digits)
    last = value % 10
    if last == 1:
        return _replace_ending(base, "いち", "いっ"), "ぱく"
    if last == 3:
        return base, "ぱく"
    if last == 6:
        return _replace_ending(base, "ろく", "ろっ"), "ぱく"
    if last == 8:
        return _replace_ending(base, "はち", "はっ"), "ぱく"
    if last == 0 and base.endswith("じゅう"):
        return base[:-1] + "っ", "ぱく"
    return base, "はく"


def _day_parts(digits: str, *, follows_month: bool) -> tuple[str, str]:
    value = int(digits)
    special = {
        1: "ついたち" if follows_month else "いちにち",
        2: "ふつか",
        3: "みっか",
        4: "よっか",
        5: "いつか",
        6: "むいか",
        7: "なのか",
        8: "ようか",
        9: "ここのか",
        10: "とおか",
        14: "じゅうよっか",
        20: "はつか",
        24: "にじゅうよっか",
    }.get(value)
    if special is None:
        return integer_reading(digits), "にち"
    if special.endswith("か"):
        return special[:-1], "か"
    if special.endswith("にち"):
        return special[:-2], "にち"
    return special, ""


def _counter_parts(
    digits: str,
    counter: str,
    *,
    follows_month: bool,
) -> tuple[NumericReadingPart, ...]:
    value = int(digits)
    number_reading: str
    counter_reading: str

    if counter == "人":
        if value == 1:
            number_reading, counter_reading = "ひと", "り"
        elif value == 2:
            number_reading, counter_reading = "ふた", "り"
        else:
            number_reading, counter_reading = integer_reading(digits), "にん"
    elif counter == "分":
        number_reading, counter_reading = _minute_parts(digits)
    elif counter == "泊":
        number_reading, counter_reading = _night_parts(digits)
    elif counter == "つ" and 1 <= value <= 10:
        whole = {
            1: "ひとつ",
            2: "ふたつ",
            3: "みっつ",
            4: "よっつ",
            5: "いつつ",
            6: "むっつ",
            7: "ななつ",
            8: "やっつ",
            9: "ここのつ",
            10: "とお",
        }[value]
        number_reading, counter_reading = (
            (whole[:-1], whole[-1]) if value != 10 else (whole, "")
        )
    elif counter == "丁目":
        number_reading, counter_reading = integer_reading(digits), "ちょうめ"
    elif counter == "月":
        number_reading = {4: "し", 7: "しち", 9: "く"}.get(
            value,
            integer_reading(digits),
        )
        counter_reading = "がつ"
    elif counter == "日":
        number_reading, counter_reading = _day_parts(
            digits,
            follows_month=follows_month,
        )
    elif counter in {"時", "時半"}:
        number_reading = {4: "よ", 7: "しち", 9: "く"}.get(
            value,
            integer_reading(digits),
        )
        counter_reading = "じ" + ("はん" if counter == "時半" else "")
    else:
        number_reading, counter_reading = integer_reading(digits), counter

    if not counter_reading:
        return (
            NumericReadingPart(
                surface=digits + counter,
                reading=number_reading,
            ),
        )
    return (
        NumericReadingPart(surface=digits, reading=number_reading),
        NumericReadingPart(surface=counter, reading=counter_reading),
    )


def resolve_numeric_span(
    surfaces: Sequence[str],
    index: int,
) -> NumericReadingSpan | None:
    digits = surfaces[index]
    if _ASCII_DIGITS.fullmatch(digits) is None:
        return None

    following = surfaces[index + 1] if index + 1 < len(surfaces) else None
    if following in _COUNTERS:
        follows_month = index >= 2 and surfaces[index - 1] == "月"
        return NumericReadingSpan(
            consumed_items=2,
            parts=_counter_parts(
                digits,
                following,
                follows_month=follows_month,
            ),
        )

    is_standard_cardinal = bool(
        following
        and _JAPANESE_TEXT.search(following)
        and not following.startswith(("、", "。"))
    )
    reading = (
        integer_reading(digits)
        if is_standard_cardinal and not (len(digits) > 1 and digits.startswith("0"))
        else "".join(_DIGIT_READINGS[int(character)] for character in digits)
    )
    return NumericReadingSpan(
        consumed_items=1,
        parts=(NumericReadingPart(surface=digits, reading=reading),),
    )
