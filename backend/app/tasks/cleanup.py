from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

from app.core.database import Database
from app.services.chunked_uploads import (
    remove_chunked_upload,
    remove_stale_audio_uploads,
)


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
        event_log_retention_days: int = 30,
        event_log_max_rows: int = 100_000,
    ) -> None:
        self.database = database
        self.storage_dir = storage_dir.resolve()
        self.retention_hours = retention_hours
        self.upload_ticket_timeout_seconds = upload_ticket_timeout_seconds
        self.upload_ticket_upload_timeout_seconds = (
            upload_ticket_upload_timeout_seconds
        )
        self.max_upload_slots = max_upload_slots
        self.event_log_retention_days = event_log_retention_days
        self.event_log_max_rows = event_log_max_rows

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
        remove_stale_audio_uploads(
            self.storage_dir,
            cutoff_timestamp=(
                current
                - timedelta(
                    seconds=self.upload_ticket_upload_timeout_seconds
                )
            ).timestamp(),
        )
        self.database.activate_upload_tickets(
            max_active_uploads=self.max_upload_slots,
        )
        event_log_cutoff = (
            current - timedelta(days=self.event_log_retention_days)
        ).isoformat()
        deleted_event_logs = self.database.cleanup_event_logs(
            older_than=event_log_cutoff,
            max_rows=self.event_log_max_rows,
        )
        if deleted_event_logs:
            self.database.record_event_log(
                level="INFO",
                category="cleanup",
                event="cleanup.event_logs_deleted",
                message="过期或超量的管理日志已清理。",
                component="cleanup_service",
                details={"deleted_count": deleted_event_logs},
            )
            self.database.cleanup_event_logs(
                older_than=event_log_cutoff,
                max_rows=self.event_log_max_rows,
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
            self.database.record_event_log(
                level="INFO",
                category="cleanup",
                event="cleanup.job_files_deleted",
                message="过期任务文件及任务记录已清理。",
                reference_type="job",
                reference_id=job_id,
                component="cleanup_service",
                details={"retention_hours": self.retention_hours},
            )
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
