from pathlib import Path
import pytest
from PIL import ImageFont

from app.subtitle import font_metrics
from app.subtitle.font_metrics import font_candidates


def test_font_candidates_prefer_the_selected_windows_font_and_weight() -> None:
    assert font_candidates("Microsoft YaHei", bold=True)[0].endswith(
        "msyhbd.ttc"
    )
    assert font_candidates("Yu Gothic", bold=False)[0].endswith(
        "YuGothM.ttc"
    )
    assert font_candidates("Yu Mincho", bold=False)[0].endswith("yumin.ttf")
    assert font_candidates("Meiryo", bold=True)[0].endswith("meiryob.ttc")


def test_font_candidates_prefer_matching_noto_weight_on_linux() -> None:
    candidates = font_candidates("Noto Sans CJK JP", bold=True)
    assert candidates[0].endswith(
        "NotoSansCJK-Bold.ttc"
    )
    assert candidates[1].endswith("NotoSansJP-VF.ttf")


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


def test_unrelated_fontconfig_fallback_does_not_override_japanese_font_candidates(
    monkeypatch,
) -> None:
    loaded_paths: list[str] = []

    class Result:
        stdout = "/fonts/DejaVuSans.ttf\n0\nDejaVu Sans\n"

    monkeypatch.setattr(font_metrics.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    def truetype(path, *args, **kwargs):
        loaded_paths.append(str(path))
        return object()

    monkeypatch.setattr(font_metrics.ImageFont, "truetype", truetype)
    font_metrics._font.cache_clear()

    font_metrics._font("Noto Sans JP", 96, False)

    assert loaded_paths[0].endswith("NotoSansCJK-Regular.ttc")
    font_metrics._font.cache_clear()


def test_exact_fontconfig_match_stays_preferred(monkeypatch) -> None:
    loaded_paths: list[str] = []

    class Result:
        stdout = "/fonts/ExampleSans.ttf\n0\nExample Sans\n"

    monkeypatch.setattr(font_metrics.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    def truetype(path, *args, **kwargs):
        loaded_paths.append(str(path))
        return object()

    monkeypatch.setattr(font_metrics.ImageFont, "truetype", truetype)
    font_metrics._font.cache_clear()

    font_metrics._font("Example Sans", 96, False)

    assert loaded_paths[0] == "/fonts/ExampleSans.ttf"
    font_metrics._font.cache_clear()


@pytest.mark.parametrize("bold,weight", [(False, 400), (True, 700)])
def test_variable_noto_uses_requested_weight(bold, weight):
    path = Path("C:/Windows/Fonts/NotoSansJP-VF.ttf")
    if not path.is_file():
        pytest.skip("Windows variable Noto fixture unavailable")
    expected = ImageFont.truetype(str(path), size=96)
    expected.set_variation_by_axes([weight])
    actual = font_metrics._font("Noto Sans JP", 96, bold)
    assert bytes(actual.getmask("国")) == bytes(expected.getmask("国"))
