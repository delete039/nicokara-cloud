from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

from app.core.database import Database


class JobCleanupService:
    def __init__(
        self,
        *,
        database: Database,
        storage_dir: Path,
        retention_hours: int,
    ) -> None:
        self.database = database
        self.storage_dir = storage_dir.resolve()
        self.retention_hours = retention_hours

    def run_once(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(UTC)
        cutoff = (current - timedelta(hours=self.retention_hours)).isoformat()
        job_ids = self.database.list_expired_terminal_job_ids(
            cutoff=cutoff
        )
        deleted: list[str] = []
        for job_id in job_ids:
            job_dir = (self.storage_dir / job_id).resolve()
            if job_dir.parent != self.storage_dir:
                continue
            shutil.rmtree(job_dir, ignore_errors=True)
            self.database.delete_job(job_id)
            deleted.append(job_id)
        return deleted


class PeriodicCleanupRunner:
    def __init__(
        self,
        service,
        *,
        interval_seconds: float,
    ) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self.service.run_once)
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _worker(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await asyncio.to_thread(self.service.run_once)
