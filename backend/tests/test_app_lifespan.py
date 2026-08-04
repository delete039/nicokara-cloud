from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.lyrics.processor import (
    LocalJapaneseLyricProcessor,
    ResilientLyricProcessor,
)
from app.tasks.runner import LocalTaskRunner
from app.vocal.mdx import MDXNetVocalRemover
from app.vocal.remover import VocalRemover


def test_app_builds_local_runner_when_processing_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        ffmpeg_path="custom-ffmpeg",
        whisper_model="tiny",
        whisper_device="cpu",
        whisper_compute_type="int8",
        video_render_preset="veryfast",
        video_render_crf=21,
        video_render_timeout_seconds=1800,
        deepseek_api_key="",
    )
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(app.state.runner, LocalTaskRunner)
        assert app.state.runner.pipeline.extractor.command == ("custom-ffmpeg",)
        assert app.state.runner.pipeline.transcriber.model_name == "tiny"
        assert app.state.runner.pipeline.transcriber.device == "cpu"
        assert app.state.runner.pipeline.transcriber.compute_type == "int8"
        assert isinstance(
            app.state.runner.pipeline.lyric_processor,
            LocalJapaneseLyricProcessor,
        )
        assert app.state.runner.pipeline.video_renderer.preset == "veryfast"
        assert app.state.runner.pipeline.video_renderer.crf == 21
        assert (
            app.state.runner.pipeline.video_renderer.timeout_seconds
            == 1800
        )


def test_app_prefers_deepseek_when_api_key_is_configured(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        deepseek_api_key="secret",
        deepseek_model="deepseek-v4-flash",
    )
    app = create_app(settings)

    with TestClient(app):
        processor = app.state.runner.pipeline.lyric_processor
        assert isinstance(processor, ResilientLyricProcessor)
        assert processor.primary.client.model == "deepseek-v4-flash"
        assert processor.primary.client.api_key == "secret"
        assert isinstance(processor.fallback, LocalJapaneseLyricProcessor)


def test_app_uses_configured_mdx_net_vocal_remover(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        vocal_removal_backend="mdx",
        vocal_removal_model="custom-karaoke.onnx",
        vocal_removal_model_dir=tmp_path / "models",
    )
    app = create_app(settings)

    with TestClient(app):
        remover = app.state.runner.pipeline.vocal_remover
        assert isinstance(remover, MDXNetVocalRemover)
        assert remover.model_filename == "custom-karaoke.onnx"
        assert remover.model_dir == tmp_path / "models"


def test_app_can_fall_back_to_stft_vocal_removal(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        vocal_removal_backend="stft",
    )
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(
            app.state.runner.pipeline.vocal_remover,
            VocalRemover,
        )
