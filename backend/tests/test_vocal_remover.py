from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from app.vocal.remover import VocalRemover


def test_removes_vocals_from_packed_stereo_pcm(tmp_path: Path) -> None:
    input_path = tmp_path / "stereo.wav"
    output_path = tmp_path / "instrumental.wav"
    sample_rate = 8000
    frame_count = 4096

    frames = bytearray()
    for index in range(frame_count):
        centre = int(8000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        side = int(3000 * math.sin(2 * math.pi * 220 * index / sample_rate))
        frames.extend(struct.pack("<hh", centre + side, centre - side))

    with wave.open(str(input_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)

    VocalRemover(fft_size=256, hop_size=64).remove_vocals(
        input_path,
        output_path,
    )

    with wave.open(str(output_path), "rb") as result:
        assert result.getnchannels() == 2
        assert result.getframerate() == sample_rate
        assert result.getnframes() > 0

