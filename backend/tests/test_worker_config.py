from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.worker_config import (
    WorkerConfigError,
    WorkerConfigReloader,
    load_worker_config,
)


def write_config(
    path: Path,
    *,
    worker_count: int,
    reload_interval_seconds: float = 0.05,
) -> None:
    path.write_text(
        "[processing]\n"
        f"worker_count = {worker_count}\n"
        f"reload_interval_seconds = {reload_interval_seconds}\n",
        encoding="utf-8",
    )


def test_repository_worker_config_defaults_to_four_workers() -> None:
    config_path = Path(__file__).parents[1] / "config" / "workers.toml"

    config = load_worker_config(config_path)

    assert config.worker_count == 4
    assert config.reload_interval_seconds == 1.0


def test_worker_config_rejects_invalid_counts(tmp_path: Path) -> None:
    config_path = tmp_path / "workers.toml"
    write_config(config_path, worker_count=0)

    with pytest.raises(WorkerConfigError, match="between 1 and 32"):
        load_worker_config(config_path)


def test_worker_config_hot_reload_updates_runner(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.worker_count = 1
            self.changed = asyncio.Event()

        async def resize_workers(self, worker_count: int) -> None:
            self.worker_count = worker_count
            self.changed.set()

    async def scenario() -> int:
        config_path = tmp_path / "workers.toml"
        write_config(config_path, worker_count=1)
        runner = RecordingRunner()
        reloader = WorkerConfigReloader(
            path=config_path,
            runner=runner,
            reload_interval_seconds=0.05,
        )
        await reloader.start()
        await asyncio.wait_for(runner.changed.wait(), 1)
        runner.changed.clear()

        write_config(config_path, worker_count=4)
        await asyncio.wait_for(runner.changed.wait(), 1)
        await reloader.stop()
        return runner.worker_count

    assert asyncio.run(scenario()) == 4
