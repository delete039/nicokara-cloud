from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class AudioExtractionError(RuntimeError):
    """Raised when FFmpeg cannot produce the analysis audio."""


class FFmpegUnavailableError(AudioExtractionError):
    """Raised when the configured FFmpeg executable cannot be started."""


class FFmpegAudioExtractor:
    def __init__(
        self,
        *,
        command: Sequence[str] = ("ffmpeg",),
        timeout_seconds: int = 900,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def extract(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            output_path.unlink(missing_ok=True)
            raise FFmpegUnavailableError(
                "FFmpeg command is not available. Check NICOKARA_FFMPEG_PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc

    def extract_stereo(self, input_path: Path, output_path: Path) -> None:
        """Extract full-quality stereo audio for vocal removal."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            output_path.unlink(missing_ok=True)
            raise FFmpegUnavailableError(
                "FFmpeg command is not available. Check NICOKARA_FFMPEG_PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc
