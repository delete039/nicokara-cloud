from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.runtime import (
    missing_processing_dependencies,
    validate_processing_runtime,
)


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "storage_dir": tmp_path / "jobs",
        "processing_enabled": True,
        "ffmpeg_path": "ffmpeg",
        "fa_kara_enabled": True,
        "vocal_removal_backend": "mdx",
    }
    values.update(overrides)
    return Settings(**values)


def test_runtime_reports_every_enabled_missing_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.runtime._executable_available",
        lambda command: False,
    )
    monkeypatch.setattr(
        "app.core.runtime._module_available",
        lambda module: False,
    )

    settings = _settings(tmp_path)

    assert missing_processing_dependencies(settings) == [
        "FFmpeg",
        "faster-whisper",
        "torch",
        "torchaudio",
        "audio-separator",
    ]
    with pytest.raises(RuntimeError, match="missing: FFmpeg, faster-whisper"):
        validate_processing_runtime(settings)


def test_runtime_ignores_disabled_optional_dependencies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.runtime._executable_available",
        lambda command: True,
    )
    monkeypatch.setattr(
        "app.core.runtime._module_available",
        lambda module: module == "faster_whisper",
    )

    settings = _settings(
        tmp_path,
        fa_kara_enabled=False,
        vocal_removal_backend="stft",
    )

    assert missing_processing_dependencies(settings) == []
    validate_processing_runtime(settings)
