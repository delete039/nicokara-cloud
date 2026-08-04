from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
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
    ) -> None:
        if pipeline is None and pipeline_factory is None:
            raise ValueError("pipeline or pipeline_factory is required")
        if worker_count <= 0:
            raise ValueError("worker_count must be greater than zero")
        if worker_count > 1 and pipeline_factory is None:
            logger.warning(
                "Multiple workers are sharing one pipeline instance; "
                "prefer pipeline_factory for thread safety."
        )
        self.pipeline = pipeline
        self.pipeline_factory = pipeline_factory
        self.max_pending_jobs = max_pending_jobs
        self.worker_count = worker_count
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._reserved_slots = 0
        self._capacity_available = asyncio.Event()
        self._capacity_available.set()
        self._worker_tasks: list[asyncio.Task[None]] = []

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
            self._worker_tasks = [
                asyncio.create_task(self._worker(worker_index))
                for worker_index in range(self.worker_count)
            ]

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
        if self._worker_tasks:
            for worker_task in self._worker_tasks:
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*self._worker_tasks)
            self._worker_tasks = []

    async def _worker(self, worker_index: int) -> None:
        pipeline = (
            self.pipeline_factory()
            if self.pipeline_factory is not None
            else self.pipeline
        )
        while True:
            job_id = await self.queue.get()
            self._update_capacity_event()
            try:
                await asyncio.to_thread(pipeline.process, job_id)
            except Exception:
                logger.exception(
                    "Background worker %s failed for job %s",
                    worker_index,
                    job_id,
                )
            finally:
                self.queue.task_done()
