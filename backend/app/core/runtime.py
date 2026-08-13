from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from app.core.config import Settings


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _executable_available(command: str) -> bool:
    candidate = Path(command)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.is_file()
    return shutil.which(command) is not None


def missing_processing_dependencies(settings: Settings) -> list[str]:
    missing: list[str] = []

    if not _executable_available(settings.ffmpeg_path):
        missing.append("FFmpeg")
    if not _module_available("faster_whisper"):
        missing.append("faster-whisper")
    if settings.fa_kara_enabled:
        if not _module_available("torch"):
            missing.append("torch")
        if not _module_available("torchaudio"):
            missing.append("torchaudio")
    if (
        settings.vocal_removal_backend == "mdx"
        and not _module_available("audio_separator")
    ):
        missing.append("audio-separator")

    return missing


def validate_processing_runtime(settings: Settings) -> None:
    missing = missing_processing_dependencies(settings)
    if not missing:
        return

    missing_text = ", ".join(missing)
    raise RuntimeError(
        "Processing runtime is incomplete; missing: "
        f"{missing_text}. Activate backend/.venv and install the AI "
        'dependencies with `pip install -e ".[ai]"` before enabling '
        "processing."
    )
