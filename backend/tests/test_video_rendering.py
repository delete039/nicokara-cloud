from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest


def test_renders_ass_with_h264_and_preserves_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        rendering_module = importlib.import_module("app.video.rendering")
    except ModuleNotFoundError:
        pytest.fail("FFmpeg video rendering module is not implemented")

    fake_ffmpeg = tmp_path / "fake ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import json
import os
import pathlib
import sys

with open(os.environ["FAKE_FFMPEG_ARGS"], "w", encoding="utf-8") as output:
    json.dump(
        {"arguments": sys.argv[1:], "cwd": os.getcwd()},
        output,
        ensure_ascii=False,
    )
pathlib.Path(sys.argv[-1]).write_bytes(
    b"\\x00\\x00\\x00\\x18ftypisom-rendered-video"
)
""".strip(),
        encoding="utf-8",
    )
    arguments_path = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_FFMPEG_ARGS", str(arguments_path))

    job_dir = tmp_path / "job with spaces"
    job_dir.mkdir()
    input_path = job_dir / "input.mp4"
    subtitle_path = job_dir / "lyrics.ass"
    output_path = job_dir / "final_karaoke.mp4"
    input_path.write_bytes(b"video")
    subtitle_path.write_text("[Script Info]\n", encoding="utf-8")

    renderer = rendering_module.FFmpegVideoRenderer(
        command=(sys.executable, str(fake_ffmpeg)),
        timeout_seconds=5,
        pad_to_16_9=False,
    )
    renderer.render(input_path, subtitle_path, output_path)

    invocation = json.loads(arguments_path.read_text(encoding="utf-8"))
    arguments = invocation["arguments"]
    assert Path(invocation["cwd"]) == job_dir
    assert arguments[arguments.index("-i") + 1] == "input.mp4"
    assert arguments[arguments.index("-vf") + 1] == (
        "subtitles=filename=lyrics.ass"
    )
    assert arguments[arguments.index("-c:v") + 1] == "libx264"
    assert arguments[arguments.index("-pix_fmt") + 1] == "yuv420p"
    assert arguments[arguments.index("-c:a") + 1] == "copy"
    assert arguments[arguments.index("-movflags") + 1] == "+faststart"
    assert arguments[-1] == "final_karaoke.mp4"
    assert output_path.stat().st_size > 0


def test_render_performance_preset_and_quality_are_configurable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendering_module = importlib.import_module("app.video.rendering")
    fake_ffmpeg = tmp_path / "fake_ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import json
import os
import pathlib
import sys
pathlib.Path(os.environ["ARGS"]).write_text(
    json.dumps(sys.argv[1:]),
    encoding="utf-8",
)
pathlib.Path(sys.argv[-1]).write_bytes(b"rendered")
""".strip(),
        encoding="utf-8",
    )
    arguments_path = tmp_path / "args.json"
    monkeypatch.setenv("ARGS", str(arguments_path))
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    input_path = job_dir / "input.mp4"
    subtitle_path = job_dir / "lyrics.ass"
    output_path = job_dir / "final_karaoke.mp4"
    input_path.write_bytes(b"video")
    subtitle_path.write_text("[Script Info]\n", encoding="utf-8")

    rendering_module.FFmpegVideoRenderer(
        command=(sys.executable, str(fake_ffmpeg)),
        preset="veryfast",
        crf=21,
    ).render(input_path, subtitle_path, output_path)

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert arguments[arguments.index("-preset") + 1] == "veryfast"
    assert arguments[arguments.index("-crf") + 1] == "21"


def test_off_vocal_maps_separated_audio_before_output_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendering_module = importlib.import_module("app.video.rendering")
    fake_ffmpeg = tmp_path / "fake_ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import json
import os
import pathlib
import sys

pathlib.Path(os.environ["ARGS"]).write_text(
    json.dumps(sys.argv[1:]),
    encoding="utf-8",
)
pathlib.Path(sys.argv[-1]).write_bytes(b"rendered")
""".strip(),
        encoding="utf-8",
    )
    arguments_path = tmp_path / "args.json"
    monkeypatch.setenv("ARGS", str(arguments_path))
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    input_path = job_dir / "input.mp4"
    subtitle_path = job_dir / "lyrics.ass"
    instrumental_path = job_dir / "audio_instrumental.wav"
    output_path = job_dir / "final_karaoke.mp4"
    input_path.write_bytes(b"video")
    subtitle_path.write_text("[Script Info]\n", encoding="utf-8")
    instrumental_path.write_bytes(b"audio")

    rendering_module.FFmpegVideoRenderer(
        command=(sys.executable, str(fake_ffmpeg)),
        pad_to_16_9=False,
    ).render(
        input_path,
        subtitle_path,
        output_path,
        vocal_mode="off",
        instrumental_audio_path=instrumental_path,
    )

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    input_indexes = [
        index
        for index, argument in enumerate(arguments)
        if argument == "-i"
    ]
    assert [arguments[index + 1] for index in input_indexes] == [
        "input.mp4",
        "audio_instrumental.wav",
    ]
    assert max(input_indexes) < arguments.index("-vf")
    map_values = [
        arguments[index + 1]
        for index, argument in enumerate(arguments)
        if argument == "-map"
    ]
    assert map_values == ["0:v:0", "1:a:0"]
    assert arguments[arguments.index("-c:a") + 1] == "aac"


def test_failed_render_removes_partial_output(tmp_path: Path) -> None:
    rendering_module = importlib.import_module("app.video.rendering")
    fake_ffmpeg = tmp_path / "failing_ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import pathlib
import sys

pathlib.Path(sys.argv[-1]).write_bytes(b"partial")
sys.stderr.write("subtitle filter failed")
raise SystemExit(2)
""".strip(),
        encoding="utf-8",
    )
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    input_path = job_dir / "input.mp4"
    subtitle_path = job_dir / "lyrics.ass"
    output_path = job_dir / "final_karaoke.mp4"
    input_path.write_bytes(b"video")
    subtitle_path.write_text("[Script Info]\n", encoding="utf-8")
    renderer = rendering_module.FFmpegVideoRenderer(
        command=(sys.executable, str(fake_ffmpeg)),
        timeout_seconds=5,
    )

    with pytest.raises(
        rendering_module.VideoRenderingError,
        match="subtitle filter failed",
    ):
        renderer.render(input_path, subtitle_path, output_path)

    assert not output_path.exists()


def test_success_without_output_is_rejected(tmp_path: Path) -> None:
    rendering_module = importlib.import_module("app.video.rendering")
    fake_ffmpeg = tmp_path / "silent_ffmpeg.py"
    fake_ffmpeg.write_text(
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    input_path = job_dir / "input.mp4"
    subtitle_path = job_dir / "lyrics.ass"
    output_path = job_dir / "final_karaoke.mp4"
    input_path.write_bytes(b"video")
    subtitle_path.write_text("[Script Info]\n", encoding="utf-8")
    renderer = rendering_module.FFmpegVideoRenderer(
        command=(sys.executable, str(fake_ffmpeg)),
        timeout_seconds=5,
    )

    with pytest.raises(
        rendering_module.VideoRenderingError,
        match="did not produce",
    ):
        renderer.render(input_path, subtitle_path, output_path)
