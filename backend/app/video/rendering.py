from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class VideoRenderingError(RuntimeError):
    """Raised when FFmpeg cannot render the karaoke video."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        timeout_seconds: float | None = None,
        stderr_tail: str | None = None,
        command: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.timeout_seconds = timeout_seconds
        self.stderr_tail = stderr_tail
        self.command = list(command) if command is not None else None


class FFmpegVideoRenderer:
    def __init__(
        self,
        *,
        command: Sequence[str] = ("ffmpeg",),
        timeout_seconds: int = 7200,
        pad_to_16_9: bool = True,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
        preset: str = "veryfast",
        crf: int = 20,
    ) -> None:
        if canvas_width <= 0 or canvas_height <= 0:
            raise ValueError("Video canvas dimensions must be positive")
        if canvas_width % 2 or canvas_height % 2:
            raise ValueError("Video canvas dimensions must be even")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self.pad_to_16_9 = pad_to_16_9
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.preset = preset
        self.crf = crf

    def render(
        self,
        input_path: Path,
        subtitle_path: Path,
        output_path: Path,
        *,
        vocal_mode: str = "on",
        instrumental_audio_path: Path | None = None,
    ) -> None:
        job_dir = input_path.parent.resolve()
        if (
            subtitle_path.parent.resolve() != job_dir
            or output_path.parent.resolve() != job_dir
        ):
            raise ValueError("Video, subtitle and output must share a directory")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            vf_parts = []
            if self.pad_to_16_9:
                # Kirakara exports to a fixed canvas: normalize non-square
                # pixels, contain the source video, then letterbox it.
                vf_parts.append(
                    "scale=w=iw*sar:h=ih:flags=lanczos,"
                    "setsar=1,"
                    f"scale=w={self.canvas_width}:h={self.canvas_height}"
                    ":force_original_aspect_ratio=decrease"
                    ":force_divisible_by=2:flags=lanczos,"
                    f"pad=w={self.canvas_width}:h={self.canvas_height}"
                    ":x=(ow-iw)/2"
                    ":y=(oh-ih)/2"
                    ":color=black,"
                    "setsar=1"
                )
            vf_parts.append(
                f"subtitles=filename={subtitle_path.name}"
            )
            cmd = [
                *self.command,
                "-y",
                "-i",
                input_path.name,
            ]
            use_instrumental = (
                vocal_mode == "off"
                and instrumental_audio_path is not None
            )
            if use_instrumental:
                cmd.extend(["-i", instrumental_audio_path.name])
            cmd.extend([
                "-vf",
                ",".join(vf_parts),
                "-map",
                "0:v:0",
            ])
            if use_instrumental:
                cmd.extend(["-map", "1:a:0"])
            else:
                cmd.extend(["-map", "0:a?"])
            cmd.extend([
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(self.crf),
                "-pix_fmt",
                "yuv420p",
            ])
            if use_instrumental:
                cmd.extend([
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                ])
            else:
                cmd.extend(["-c:a", "copy"])
            cmd.extend(["-movflags", "+faststart", output_path.name])
            subprocess.run(
                cmd,
                cwd=job_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                output_path.unlink(missing_ok=True)
                raise VideoRenderingError(
                    "FFmpeg did not produce a non-empty output video"
                )
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise VideoRenderingError(
                "FFmpeg video rendering timed out",
                timeout_seconds=self.timeout_seconds,
                stderr_tail=str(exc.stderr or "")[-2000:],
                command=cmd,
            ) from exc
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise VideoRenderingError(
                detail[-2000:],
                exit_code=exc.returncode,
                stderr_tail=detail[-2000:],
                command=cmd,
            ) from exc
