"""Measure real libass pixels, not just the generated ASS strings."""
import io
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from app.alignment.models import AlignedLine, AlignedToken, LyricTimeline
from app.subtitle.font_metrics import _font
from app.subtitle.kirakara_generator import KirakaraAssConfig, KirakaraAssGenerator


@pytest.mark.parametrize("width,height", [(1920, 1080), (1280, 720)])
@pytest.mark.parametrize("bold", [False, True])
def test_libass_glyph_size_matches_css_em_size(tmp_path, width, height, bold):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    font = _font("Noto Sans JP", 96, bold)
    family = font.getname()[0]
    config = KirakaraAssConfig.from_browser_style({
        "font_family": family, "font_bold": bold, "stroke_width": 0,
    })
    timeline = LyricTimeline(confidence=1, lines=[
        AlignedLine("国", "くに", 5000, 7000, 1, [AlignedToken("国", "くに", 5000, 7000, 1)]),
    ])
    (tmp_path / "test.ass").write_text(KirakaraAssGenerator(config=config).generate(timeline), encoding="utf-8-sig")
    result = subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=1920x1080:r=2:d=6",
        "-vf", f"subtitles=test.ass,scale={width}:{height}", "-ss", "4.5", "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "png", "-",
    ], cwd=tmp_path, capture_output=True, check=True, timeout=30)
    actual = Image.open(io.BytesIO(result.stdout)).convert("L")
    actual_box = actual.crop((0, round(640 * height / 1080), width, height)).point(lambda pixel: 255 if pixel > 64 else 0).getbbox()
    expected = Image.new("L", (1920, 1080))
    # Chromium DOM measured baseline for Noto Sans JP 96px / line-height 1.2.
    # This independent browser observation guards the CSS-to-ASS top offset.
    ImageDraw.Draw(expected).text((192, 645 + 99.3333), "国", font=font, fill=255, anchor="ls")
    ruby_font = _font(family, 39, False)
    for character, x in [("く", 197.25), ("に", 243.75)]:
        ImageDraw.Draw(expected).text((x, 634.556), character, font=ruby_font, fill=255, anchor="ls")
    expected = expected.resize((width, height))
    expected_box = expected.crop((0, round(640 * height / 1080), width, height)).point(lambda pixel: 255 if pixel > 64 else 0).getbbox()
    assert actual_box and expected_box
    actual_width = actual_box[2] - actual_box[0]
    expected_width = expected_box[2] - expected_box[0]
    assert abs(actual_width - expected_width) <= 3, (actual_box, expected_box)
    assert max(abs(a - b) for a, b in zip(actual_box, expected_box)) <= 3, (actual_box, expected_box)
    ruby_crop = (0, round(580 * height / 1080), width, round(640 * height / 1080))
    actual_ruby = actual.crop(ruby_crop).point(lambda pixel: 255 if pixel > 64 else 0).getbbox()
    expected_ruby = expected.crop(ruby_crop).point(lambda pixel: 255 if pixel > 64 else 0).getbbox()
    assert actual_ruby and expected_ruby
    assert max(abs(a - b) for a, b in zip(actual_ruby, expected_ruby)) <= 3, (actual_ruby, expected_ruby)
