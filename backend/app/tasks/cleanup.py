from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

from app.core.database import Database
from app.services.chunked_uploads import remove_chunked_upload


class JobCleanupService:
    def __init__(
        self,
        *,
        database: Database,
        storage_dir: Path,
        retention_hours: int,
        upload_ticket_timeout_seconds: int = 120,
        upload_ticket_upload_timeout_seconds: int = 3600,
        max_upload_slots: int = 1,
    ) -> None:
        self.database = database
        self.storage_dir = storage_dir.resolve()
        self.retention_hours = retention_hours
        self.upload_ticket_timeout_seconds = upload_ticket_timeout_seconds
        self.upload_ticket_upload_timeout_seconds = (
            upload_ticket_upload_timeout_seconds
        )
        self.max_upload_slots = max_upload_slots

    def run_once(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(UTC)
        expired_ticket_ids = self.database.expire_stale_upload_tickets(
            waiting_cutoff=(
                current
                - timedelta(seconds=self.upload_ticket_timeout_seconds)
            ).isoformat(),
            uploading_cutoff=(
                current
                - timedelta(
                    seconds=self.upload_ticket_upload_timeout_seconds
                )
            ).isoformat(),
        )
        for ticket_id in expired_ticket_ids:
            remove_chunked_upload(self.storage_dir, ticket_id)
        self.database.activate_upload_tickets(
            max_active_uploads=self.max_upload_slots,
        )
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
