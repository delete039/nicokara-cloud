from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
from pathlib import Path
import tomllib
from typing import Protocol


logger = logging.getLogger(__name__)


class ResizableRunner(Protocol):
    async def resize_workers(self, worker_count: int) -> None: ...


class WorkerConfigError(ValueError):
    """Raised when the worker configuration file is invalid."""


@dataclass(frozen=True)
class WorkerConfig:
    worker_count: int
    reload_interval_seconds: float

    @classmethod
    def from_bytes(cls, content: bytes) -> "WorkerConfig":
        try:
            document = tomllib.loads(content.decode("utf-8"))
            processing = document["processing"]
            worker_count = processing["worker_count"]
            reload_interval_seconds = processing.get(
                "reload_interval_seconds",
                1.0,
            )
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            tomllib.TOMLDecodeError,
        ) as exc:
            raise WorkerConfigError(
                "workers.toml must contain a valid [processing] section"
            ) from exc

        if isinstance(worker_count, bool) or not isinstance(worker_count, int):
            raise WorkerConfigError("processing.worker_count must be an integer")
        if not 1 <= worker_count <= 32:
            raise WorkerConfigError(
                "processing.worker_count must be between 1 and 32"
            )
        if isinstance(reload_interval_seconds, bool) or not isinstance(
            reload_interval_seconds,
            (int, float),
        ):
            raise WorkerConfigError(
                "processing.reload_interval_seconds must be a number"
            )
        if reload_interval_seconds < 0.05:
            raise WorkerConfigError(
                "processing.reload_interval_seconds must be at least 0.05"
            )
        return cls(
            worker_count=worker_count,
            reload_interval_seconds=float(reload_interval_seconds),
        )


def load_worker_config(path: Path) -> WorkerConfig:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise WorkerConfigError(
            f"Unable to read worker configuration: {path}"
        ) from exc
    return WorkerConfig.from_bytes(content)


class WorkerConfigReloader:
    def __init__(
        self,
        *,
        path: Path,
        runner: ResizableRunner,
        reload_interval_seconds: float,
    ) -> None:
        self.path = path
        self.runner = runner
        self.reload_interval_seconds = reload_interval_seconds
        self._last_content: bytes | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _watch(self) -> None:
        while True:
            await self._reload_if_changed()
            await asyncio.sleep(self.reload_interval_seconds)

    async def _reload_if_changed(self) -> None:
        try:
            content = self.path.read_bytes()
            if content == self._last_content:
                return
            config = WorkerConfig.from_bytes(content)
            await self.runner.resize_workers(config.worker_count)
        except (OSError, WorkerConfigError) as exc:
            message = str(exc)
            if message != self._last_error:
                logger.error(
                    "Worker configuration reload failed; keeping the "
                    "last valid worker count: %s",
                    message,
                )
                self._last_error = message
            return

        self.reload_interval_seconds = config.reload_interval_seconds
        self._last_content = content
        self._last_error = None
        logger.info(
            "Worker configuration reloaded from %s: worker_count=%s",
            self.path,
            config.worker_count,
        )
