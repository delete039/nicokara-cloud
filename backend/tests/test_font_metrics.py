from pathlib import Path

from app.subtitle import font_metrics
from app.subtitle.font_metrics import font_candidates


def test_font_candidates_prefer_the_selected_windows_font_and_weight() -> None:
    assert font_candidates("Microsoft YaHei", bold=True)[0].endswith(
        "msyhbd.ttc"
    )
    assert font_candidates("Yu Gothic", bold=False)[0].endswith(
        "YuGothM.ttc"
    )


def test_font_candidates_prefer_matching_noto_weight_on_linux() -> None:
    assert font_candidates("Noto Sans CJK JP", bold=True)[0].endswith(
        "NotoSansCJK-Bold.ttc"
    )


def test_fontconfig_query_requests_the_rendered_weight(monkeypatch) -> None:
    commands: list[list[str]] = []

    class Result:
        stdout = ""

    def run(command, **kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(font_metrics.subprocess, "run", run)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    monkeypatch.setattr(font_metrics.ImageFont, "truetype", lambda *args, **kwargs: object())
    font_metrics._font.cache_clear()

    font_metrics.text_measurer("Noto Sans CJK JP", 96, bold=True)

    assert commands[0][-1] == "Noto Sans CJK JP:style=Bold"
    font_metrics._font.cache_clear()
