from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from app.core.event_logging import event_context, exception_details


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
        event_logger: Any | None = None,
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
        self.event_logger = event_logger
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued_at: dict[str, deque[float]] = defaultdict(deque)
        self._reserved_slots = 0
        self._capacity_available = asyncio.Event()
        self._capacity_available.set()
        self._worker_tasks: dict[int, asyncio.Task[None]] = {}
        self._started = False
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
        self._queued_at[job_id].append(time.perf_counter())
        self.queue.put_nowait(job_id)
        self._record_queued(job_id)
        self._update_capacity_event()

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._last_heartbeat_at = datetime.now(UTC)
        self._ensure_workers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def resize_workers(self, worker_count: int) -> None:
        if worker_count <= 0:
            raise ValueError("worker_count must be greater than zero")
        previous_count = self.worker_count
        if worker_count == previous_count:
            return
        if worker_count > 1 and self.pipeline_factory is None:
            logger.warning(
                "Multiple workers are sharing one pipeline instance; "
                "prefer pipeline_factory for thread safety."
            )
        self.worker_count = worker_count
        if self._started:
            self._ensure_workers()
        logger.info(
            "Background worker count changed from %s to %s",
            previous_count,
            worker_count,
        )

    @property
    def active_worker_count(self) -> int:
        return sum(
            not task.done() for task in self._worker_tasks.values()
        )

    def _ensure_workers(self) -> None:
        for worker_index in range(self.worker_count):
            task = self._worker_tasks.get(worker_index)
            if task is None or task.done():
                self._worker_tasks[worker_index] = asyncio.create_task(
                    self._worker(worker_index)
                )

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        alive_workers = self.active_worker_count
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
        self._queued_at[job_id].append(time.perf_counter())
        self.queue.put_nowait(job_id)
        self._record_queued(job_id)
        self._update_capacity_event()

    def _record_queued(self, job_id: str) -> None:
        if self.event_logger is None:
            return
        self.event_logger.emit(
            event="job.queued",
            level="INFO",
            category="queue",
            message="任务已进入处理队列",
            job_id=job_id,
            component="task_runner",
            details={"queue_length": self.queue.qsize()},
        )

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
                timestamps = self._queued_at.get(queued_job_id)
                if timestamps:
                    timestamps.popleft()
            else:
                retained_job_ids.append(queued_job_id)

        for queued_job_id in retained_job_ids:
            self.queue.put_nowait(queued_job_id)
        self._update_capacity_event()
        return removed

    async def stop(self) -> None:
        await self.queue.join()
        self._started = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._worker_tasks:
            worker_tasks = list(self._worker_tasks.values())
            for worker_task in worker_tasks:
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*worker_tasks)
            self._worker_tasks = {}

    async def _heartbeat(self) -> None:
        while True:
            self._last_heartbeat_at = datetime.now(UTC)
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _worker(self, worker_index: int) -> None:
        if worker_index == 0 and self.pipeline is not None:
            pipeline = self.pipeline
        elif self.pipeline_factory is not None:
            pipeline = self.pipeline_factory()
        else:
            pipeline = self.pipeline
        while self._started and worker_index < self.worker_count:
            try:
                job_id = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=0.5,
                )
            except TimeoutError:
                continue
            self._update_capacity_event()
            self._active_jobs[worker_index] = (job_id, datetime.now(UTC))
            timestamps = self._queued_at.get(job_id)
            queued_at = timestamps.popleft() if timestamps else time.perf_counter()
            if timestamps is not None and not timestamps:
                self._queued_at.pop(job_id, None)
            run_id = str(uuid4())
            queue_wait_ms = max((time.perf_counter() - queued_at) * 1000, 0)
            with event_context(
                job_id=job_id,
                run_id=run_id,
                component="task_runner",
            ):
                if self.event_logger is not None:
                    self.event_logger.emit(
                        event="worker.assigned",
                        level="INFO",
                        category="queue",
                        message="worker 已领取任务",
                        details={
                            "worker_index": worker_index,
                            "queue_wait_ms": round(queue_wait_ms, 3),
                            "queue_length": self.queue.qsize(),
                        },
                    )
                started = time.perf_counter()
                try:
                    await asyncio.to_thread(pipeline.process, job_id)
                except Exception as exc:
                    safe_error = exception_details(exc, include_traceback=False)
                    logger.error(
                        "Background worker %s failed for job %s (%s: %s)",
                        worker_index,
                        job_id,
                        safe_error["exception_type"],
                        safe_error["error_summary"],
                    )
                    if self.event_logger is not None:
                        self.event_logger.emit(
                            event="worker.failed",
                            level="ERROR",
                            category="queue",
                            message="worker 执行任务失败",
                            duration_ms=(time.perf_counter() - started) * 1000,
                            details={
                                "worker_index": worker_index,
                                **exception_details(exc),
                            },
                        )
                else:
                    if self.event_logger is not None:
                        self.event_logger.emit(
                            event="worker.released",
                            level="INFO",
                            category="queue",
                            message="worker 已完成本次任务运行",
                            duration_ms=(time.perf_counter() - started) * 1000,
                            details={"worker_index": worker_index},
                        )
                finally:
                    self._active_jobs.pop(worker_index, None)
                    self.queue.task_done()
