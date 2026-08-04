from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any


logger = logging.getLogger(__name__)


class QueueCapacityError(RuntimeError):
    """Raised when the local processing queue is full."""


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
        pipeline: Any,
        *,
        max_pending_jobs: int = 4,
    ) -> None:
        self.pipeline = pipeline
        self.max_pending_jobs = max_pending_jobs
        self.queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=max_pending_jobs
        )
        self._reserved_slots = 0
        self._capacity_available = asyncio.Event()
        self._capacity_available.set()
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def can_accept(self) -> bool:
        return self.queue.qsize() + self._reserved_slots < self.max_pending_jobs

    def _update_capacity_event(self) -> None:
        if self.can_accept:
            self._capacity_available.set()
        else:
            self._capacity_available.clear()

    def reserve(self) -> QueueReservation:
        if not self.can_accept:
            raise QueueCapacityError("The processing queue is full")
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
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull as exc:
            raise RuntimeError("Reserved queue capacity was lost") from exc
        self._update_capacity_event()

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def enqueue(self, job_id: str) -> None:
        if not self.can_accept:
            raise QueueCapacityError("The processing queue is full")
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull as exc:
            raise QueueCapacityError(
                "The processing queue is full"
            ) from exc
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
        if self._worker_task is not None:
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            self._update_capacity_event()
            try:
                await asyncio.to_thread(self.pipeline.process, job_id)
            except Exception:
                logger.exception("Background processing failed for job %s", job_id)
            finally:
                self.queue.task_done()
