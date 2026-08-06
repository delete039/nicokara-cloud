from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Callable


logger = logging.getLogger(__name__)


class QueueCapacityError(RuntimeError):
    """Compatibility error for older bounded queue integrations."""


class QueueReservation:
    def __init__(self, runner: "LocalTaskRunner") -> None:
        self._runner = runner
        self._active = True

    async def enqueue(self, job_id: str) -> None:
        if not self._active:
            raise RuntimeError("Queue reservation is no longer active")
        self._active = False
        self._runner._enqueue_reserved(job_id)

    def release(self) -> None:
        if self._active:
            self._active = False
            self._runner._release_reservation()


class LocalTaskRunner:
    def __init__(
        self,
        pipeline: Any | None = None,
        *,
        pipeline_factory: Callable[[], Any] | None = None,
        max_pending_jobs: int = 4,
        worker_count: int = 1,
        heartbeat_interval_seconds: float = 5,
    ) -> None:
        if pipeline is None and pipeline_factory is None:
            raise ValueError("pipeline or pipeline_factory is required")
        if worker_count <= 0:
            raise ValueError("worker_count must be greater than zero")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than zero")
        if worker_count > 1 and pipeline_factory is None:
            logger.warning(
                "Multiple workers are sharing one pipeline instance; "
                "prefer pipeline_factory for thread safety."
        )
        self.pipeline = pipeline
        self.pipeline_factory = pipeline_factory
        self.max_pending_jobs = max_pending_jobs
        self.worker_count = worker_count
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._reserved_slots = 0
        self._capacity_available = asyncio.Event()
        self._capacity_available.set()
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._last_heartbeat_at: datetime | None = None
        self._active_jobs: dict[int, tuple[str, datetime]] = {}

    @property
    def can_accept(self) -> bool:
        return True

    def _update_capacity_event(self) -> None:
        self._capacity_available.set()

    def reserve(self) -> QueueReservation:
        self._reserved_slots += 1
        self._update_capacity_event()
        return QueueReservation(self)

    def _release_reservation(self) -> None:
        if self._reserved_slots <= 0:
            raise RuntimeError("Queue reservation accounting is invalid")
        self._reserved_slots -= 1
        self._update_capacity_event()

    def _enqueue_reserved(self, job_id: str) -> None:
        self._release_reservation()
        self.queue.put_nowait(job_id)
        self._update_capacity_event()

    async def start(self) -> None:
        if not self._worker_tasks:
            self._last_heartbeat_at = datetime.now(UTC)
            self._worker_tasks = [
                asyncio.create_task(self._worker(worker_index))
                for worker_index in range(self.worker_count)
            ]
            self._heartbeat_task = asyncio.create_task(self._heartbeat())

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        alive_workers = sum(not task.done() for task in self._worker_tasks)
        heartbeat_age = (
            (now - self._last_heartbeat_at).total_seconds()
            if self._last_heartbeat_at is not None
            else None
        )
        healthy = (
            alive_workers == self.worker_count
            and self.worker_count > 0
            and heartbeat_age is not None
            and heartbeat_age <= max(5, self.heartbeat_interval_seconds * 3)
        )
        return {
            "healthy": healthy,
            "worker_count": self.worker_count,
            "alive_workers": alive_workers,
            "queued_in_memory": self.queue.qsize(),
            "last_heartbeat_at": (
                self._last_heartbeat_at.isoformat()
                if self._last_heartbeat_at is not None
                else None
            ),
            "active_jobs": [
                {
                    "worker_index": worker_index,
                    "job_id": job_id,
                    "started_at": started_at.isoformat(),
                }
                for worker_index, (job_id, started_at) in sorted(
                    self._active_jobs.items()
                )
            ],
        }

    async def enqueue(self, job_id: str) -> None:
        self.queue.put_nowait(job_id)
        self._update_capacity_event()

    async def enqueue_wait(self, job_id: str) -> None:
        while True:
            try:
                reservation = self.reserve()
            except QueueCapacityError:
                await self._capacity_available.wait()
                continue
            await reservation.enqueue(job_id)
            return

    async def cancel(self, job_id: str) -> bool:
        retained_job_ids: list[str] = []
        removed = False
        while True:
            try:
                queued_job_id = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.queue.task_done()
            if queued_job_id == job_id and not removed:
                removed = True
            else:
                retained_job_ids.append(queued_job_id)

        for queued_job_id in retained_job_ids:
            self.queue.put_nowait(queued_job_id)
        self._update_capacity_event()
        return removed

    async def stop(self) -> None:
        await self.queue.join()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._worker_tasks:
            for worker_task in self._worker_tasks:
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*self._worker_tasks)
            self._worker_tasks = []

    async def _heartbeat(self) -> None:
        while True:
            self._last_heartbeat_at = datetime.now(UTC)
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _worker(self, worker_index: int) -> None:
        pipeline = (
            self.pipeline_factory()
            if self.pipeline_factory is not None
            else self.pipeline
        )
        while True:
            job_id = await self.queue.get()
            self._update_capacity_event()
            self._active_jobs[worker_index] = (job_id, datetime.now(UTC))
            try:
                await asyncio.to_thread(pipeline.process, job_id)
            except Exception:
                logger.exception(
                    "Background worker %s failed for job %s",
                    worker_index,
                    job_id,
                )
            finally:
                self._active_jobs.pop(worker_index, None)
                self.queue.task_done()
