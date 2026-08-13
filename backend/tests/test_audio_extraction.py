from __future__ import annotations

import importlib
import json
import os
import sys
import wave
from pathlib import Path

import pytest


def test_extracts_16khz_mono_pcm_without_shell_interpolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        audio_module = importlib.import_module("app.video.audio")
    except ModuleNotFoundError:
        pytest.fail("FFmpeg audio extraction module is not implemented")

    fake_ffmpeg = tmp_path / "fake ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import json
import os
import sys
import wave

arguments = sys.argv[1:]
with open(os.environ["FAKE_FFMPEG_ARGS"], "w", encoding="utf-8") as output:
    json.dump(arguments, output, ensure_ascii=False)

with wave.open(arguments[-1], "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(16000)
    output.writeframes(b"\\x00\\x00" * 160)
""".strip(),
        encoding="utf-8",
    )
    arguments_path = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_FFMPEG_ARGS", str(arguments_path))

    input_path = tmp_path / "song with spaces.mp4"
    input_path.write_bytes(b"fake mp4")
    output_path = tmp_path / "analysis audio.wav"

    extractor = audio_module.FFmpegAudioExtractor(
        command=(sys.executable, str(fake_ffmpeg)),
        timeout_seconds=5,
    )
    extractor.extract(input_path, output_path)

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert arguments[arguments.index("-i") + 1] == str(input_path)
    assert arguments[-1] == str(output_path)
    assert "-vn" in arguments
    assert arguments[arguments.index("-ac") + 1] == "1"
    assert arguments[arguments.index("-ar") + 1] == "16000"
    assert arguments[arguments.index("-c:a") + 1] == "pcm_s16le"
    with wave.open(str(output_path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getsampwidth() == 2


def test_failed_extraction_removes_partial_output(tmp_path: Path) -> None:
    audio_module = importlib.import_module("app.video.audio")
    fake_ffmpeg = tmp_path / "failing_ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import pathlib
import sys

pathlib.Path(sys.argv[-1]).write_bytes(b"partial")
sys.stderr.write("decoder failed")
raise SystemExit(3)
""".strip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "audio.wav"
    extractor = audio_module.FFmpegAudioExtractor(
        command=(sys.executable, str(fake_ffmpeg)),
        timeout_seconds=5,
    )

    with pytest.raises(audio_module.AudioExtractionError, match="decoder failed"):
        extractor.extract(tmp_path / "input.mp4", output_path)

    assert not output_path.exists()


def test_missing_ffmpeg_is_reported_as_unavailable_tool(tmp_path: Path) -> None:
    audio_module = importlib.import_module("app.video.audio")
    output_path = tmp_path / "audio.wav"
    extractor = audio_module.FFmpegAudioExtractor(
        command=(str(tmp_path / "missing-ffmpeg.exe"),),
        timeout_seconds=5,
    )

    with pytest.raises(
        audio_module.FFmpegUnavailableError,
        match="FFmpeg",
    ):
        extractor.extract(tmp_path / "input.m4a", output_path)

    assert not output_path.exists()
