from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.video.formats import (
    SUPPORTED_VIDEO_SUFFIXES,
    is_supported_video_name,
    looks_like_video,
)


SIGNATURES = {
    ".mp4": b"\x00\x00\x00\x18ftypisom",
    ".mov": b"\x00\x00\x00\x18ftypqt  ",
    ".mkv": b"\x1a\x45\xdf\xa3\x93\x42\x82\x88",
    ".webm": b"\x1a\x45\xdf\xa3\x93\x42\x82\x88",
    ".avi": b"RIFF\x00\x00\x00\x00AVI ",
    ".wmv": bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C"),
    ".flv": b"FLV\x01\x05\x00\x00\x00\x09",
    ".ts": b"\x47" + b"\x00" * 187,
    ".mpeg": b"\x00\x00\x01\xba",
    ".ogv": b"OggS" + b"\x00" * 8,
}


@pytest.mark.parametrize("suffix", sorted(SUPPORTED_VIDEO_SUFFIXES))
def test_common_video_extensions_are_supported(suffix: str) -> None:
    assert is_supported_video_name(f"sample{suffix.upper()}")


@pytest.mark.parametrize(("suffix", "header"), SIGNATURES.items())
def test_common_container_signatures_are_checked(suffix: str, header: bytes) -> None:
    assert looks_like_video(header, suffix)
    assert not looks_like_video(b"not-a-video", suffix)


def test_m2ts_accepts_the_four_byte_packet_prefix() -> None:
    assert looks_like_video(b"\x00\x00\x00\x01\x47", ".m2ts")


FFMPEG_FORMATS = {
    ".mp4": ["-c:v", "libx264", "-c:a", "aac", "-f", "mp4"],
    ".mov": ["-c:v", "libx264", "-c:a", "aac", "-f", "mov"],
    ".mkv": ["-c:v", "libx264", "-c:a", "aac", "-f", "matroska"],
    ".webm": ["-c:v", "libvpx-vp9", "-c:a", "libopus", "-f", "webm"],
    ".avi": ["-c:v", "mpeg4", "-c:a", "libmp3lame", "-f", "avi"],
    ".wmv": ["-c:v", "wmv2", "-c:a", "wmav2", "-f", "asf"],
    ".flv": ["-c:v", "flv", "-c:a", "aac", "-ar", "44100", "-f", "flv"],
    ".mpeg": ["-c:v", "mpeg2video", "-c:a", "mp2", "-f", "mpeg"],
    ".ts": ["-c:v", "mpeg2video", "-c:a", "mp2", "-f", "mpegts"],
    ".3gp": ["-vf", "scale=176:144", "-c:v", "h263", "-c:a", "aac", "-f", "3gp"],
    ".ogv": ["-c:v", "libtheora", "-c:a", "libvorbis", "-f", "ogg"],
}


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
@pytest.mark.parametrize(("suffix", "format_args"), FFMPEG_FORMATS.items())
def test_ffmpeg_can_decode_common_video_containers(
    tmp_path: Path,
    suffix: str,
    format_args: list[str],
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    source = tmp_path / "source.mp4"
    output = tmp_path / f"sample{suffix}"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *format_args, str(output)],
        check=True,
    )
    header = output.read_bytes()[:32]
    assert looks_like_video(header, suffix)
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            "-",
        ],
        check=True,
    )
    rendered = tmp_path / f"rendered-from{suffix}.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(rendered),
        ],
        check=True,
    )
    assert rendered.is_file() and rendered.stat().st_size > 0
