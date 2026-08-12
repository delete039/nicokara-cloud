from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
import subprocess

from PIL import ImageFont


def font_candidates(font_name: str, *, bold: bool) -> list[str]:
    windows_fonts = {
        "Microsoft YaHei": (
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"
        ),
        "Yu Gothic": (
            "C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc"
        ),
    }
    noto = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    )
    preferred = windows_fonts.get(font_name, noto)
    return [
        preferred,
        noto,
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]


@lru_cache(maxsize=16)
def _font(font_name: str, size: int, bold: bool):
    candidates: list[str] = []
    try:
        result = subprocess.run(
            [
                "fc-match",
                "-f",
                "%{file}",
                f"{font_name}:style={'Bold' if bold else 'Regular'}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip():
            candidates.append(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    candidates.extend(font_candidates(font_name, bold=bold))
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.truetype(font_name, size=size)


def text_measurer(
    font_name: str,
    size: int,
    *,
    bold: bool = False,
) -> Callable[[str], float]:
    font = _font(font_name, size, bold)
    return lambda text: float(font.getlength(text))
