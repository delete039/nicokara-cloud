from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import subprocess
import struct

from PIL import ImageFont


def font_candidates(font_name: str, *, bold: bool) -> list[str]:
    windows_fonts = {
        "Noto Sans CJK JP": "C:/Windows/Fonts/NotoSansJP-VF.ttf",
        "Noto Sans JP": "C:/Windows/Fonts/NotoSansJP-VF.ttf",
        "Microsoft YaHei": (
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"
        ),
        "Meiryo": (
            "C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc"
        ),
        "Yu Gothic": (
            "C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc"
        ),
        "Yu Mincho": (
            "C:/Windows/Fonts/yumindb.ttf" if bold else "C:/Windows/Fonts/yumin.ttf"
        ),
    }
    noto = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    )
    windows_preferred = windows_fonts.get(font_name, noto)
    preferred = (
        noto
        if font_name in {"Noto Sans CJK JP", "Noto Sans JP"}
        else windows_preferred
    )
    return [
        preferred,
        windows_preferred,
        noto,
        "C:/Windows/Fonts/NotoSansJP-VF.ttf",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]


@lru_cache(maxsize=16)
def _font(font_name: str, size: int, bold: bool):
    candidates: list[tuple[str, int]] = []
    try:
        result = subprocess.run(
            [
                "fc-match",
                "-f",
                "%{file}\n%{index}",
                f"{font_name}:style={'Bold' if bold else 'Regular'}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip():
            parts = result.stdout.strip().splitlines()
            candidates.append((parts[0], int(parts[1]) & 0xFFFF if len(parts) > 1 else 0))
    except (OSError, subprocess.SubprocessError):
        pass
    candidates.extend((path, 0) for path in font_candidates(font_name, bold=bold))
    for candidate, index in candidates:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, size=size, index=index)
            try:
                axes = font.get_variation_axes()
                font.set_variation_by_axes([
                    min(axis["maximum"], max(axis["minimum"], 700 if bold else 400))
                    if axis["name"] == b"Weight" else axis["default"]
                    for axis in axes
                ])
            except (OSError, AttributeError):
                pass  # Static font, already selected by family and weight.
            return font
    return ImageFont.truetype(font_name, size=size)


@dataclass(frozen=True)
class AssFontGeometry:
    family: str
    size_ratio: float
    ascent: float
    css_ascent: float
    css_descent: float

    def top_offset(self, size: float, line_height: float) -> float:
        # DOM line box baseline minus libass's WinAscent top bearing.
        return size * ((line_height + self.css_ascent - self.css_descent) / 2 - self.ascent)


@lru_cache(maxsize=32)
def ass_font_geometry(font_name: str, bold: bool = False) -> AssFontGeometry:
    """Convert CSS em sizing to libass REAL_DIM sizing for the same font face.

    Read only the small SFNT metrics tables; support both TTF/OTF and TTC.
    libass uses OS/2 WinAscent/WinDescent, falling back to face metrics.
    """
    font = _font(font_name, 1000, bold)
    with open(font.path, "rb") as source:
        signature = source.read(4)
        offset = 0
        if signature == b"ttcf":
            source.seek(12 + 4 * font.index)
            offset = struct.unpack(">I", source.read(4))[0]
        source.seek(offset + 4)
        count = struct.unpack(">H", source.read(2))[0]
        source.seek(offset + 12)
        tables = {}
        for _ in range(count):
            tag, _, position, length = struct.unpack(">4sIII", source.read(16))
            tables[tag] = (position, length)

        def table(tag: bytes) -> bytes:
            if tag not in tables:
                return b""
            position, length = tables[tag]
            source.seek(position)
            return source.read(min(length, 128))

        head, hhea, os2 = table(b"head"), table(b"hhea"), table(b"OS/2")
    em = struct.unpack_from(">H", head, 18)[0]
    asc, desc = struct.unpack_from(">hh", hhea, 4)
    win_asc, win_desc = asc, -desc
    if len(os2) >= 78:
        win_asc, win_desc = struct.unpack_from(">hh", os2, 74)
        if win_asc + win_desc <= 0:
            win_asc, win_desc = asc, -desc
    return AssFontGeometry(font.getname()[0], (win_asc + win_desc) / em,
                           win_asc / em, win_asc / em, win_desc / em)


def text_measurer(
    font_name: str,
    size: int,
    *,
    bold: bool = False,
) -> Callable[[str], float]:
    font = _font(font_name, size, bold)
    return lambda text: float(font.getlength(text))


def text_ink_measurer(
    font_name: str,
    size: int,
    *,
    bold: bool = False,
) -> Callable[[str], tuple[float, float]]:
    """Return Canvas-compatible ink distances left and right of the glyph origin."""
    font = _font(font_name, size, bold)

    def measure(text: str) -> tuple[float, float]:
        left, _top, right, _bottom = font.getbbox(text)
        return max(0.0, -float(left)), max(0.0, float(right))

    return measure
