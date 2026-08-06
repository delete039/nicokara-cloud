from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

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


def test_app_uses_configured_processing_worker_count(
    tmp_path: Path,
) -> None:
    worker_config_path = tmp_path / "workers.toml"
    worker_config_path.write_text(
        "[processing]\n"
        "worker_count = 2\n"
        "reload_interval_seconds = 0.05\n",
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        worker_config_path=worker_config_path,
    )
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(app.state.runner, LocalTaskRunner)
        assert app.state.runner.worker_count == 2


def test_app_hot_reloads_processing_worker_count(tmp_path: Path) -> None:
    worker_config_path = tmp_path / "workers.toml"
    worker_config_path.write_text(
        "[processing]\n"
        "worker_count = 1\n"
        "reload_interval_seconds = 0.05\n",
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=True,
        worker_config_path=worker_config_path,
    )
    app = create_app(settings)

    with TestClient(app):
        worker_config_path.write_text(
            "[processing]\n"
            "worker_count = 4\n"
            "reload_interval_seconds = 0.05\n",
            encoding="utf-8",
        )
        deadline = time.monotonic() + 2
        while app.state.runner.worker_count != 4:
            if time.monotonic() >= deadline:
                pytest.fail("worker count was not hot reloaded")
            time.sleep(0.02)

        snapshot = app.state.runner.snapshot()
        assert app.state.runner.active_worker_count == 4
        assert snapshot["worker_count"] == 4
        assert snapshot["alive_workers"] == 4


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


def test_cors_preflight_allows_common_local_frontend_origins(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        for origin in (
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://[::1]:3000",
        ):
            response = client.options(
                "/api/v1/jobs",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )

            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
