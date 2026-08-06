from __future__ import annotations

import asyncio
from datetime import datetime
import importlib
import threading

import pytest


def test_runner_processes_jobs_sequentially_and_survives_failure() -> None:
    try:
        runner_module = importlib.import_module("app.tasks.runner")
    except ModuleNotFoundError:
        pytest.fail("Local task runner is not implemented")

    class RecordingPipeline:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.completed = threading.Event()

        def process(self, job_id: str) -> None:
            self.calls.append(job_id)
            if job_id == "first":
                raise RuntimeError("expected failure")
            self.completed.set()

    async def scenario() -> list[str]:
        pipeline = RecordingPipeline()
        runner = runner_module.LocalTaskRunner(pipeline)
        await runner.start()
        await runner.enqueue("first")
        await runner.enqueue("second")
        completed = await asyncio.to_thread(pipeline.completed.wait, 2)
        await runner.stop()
        assert completed
        return pipeline.calls

    assert asyncio.run(scenario()) == ["first", "second"]


def test_runner_can_process_jobs_with_multiple_workers() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class SharedState:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.release = threading.Event()
            self.both_started = threading.Event()
            self.active = 0
            self.max_active = 0
            self.started: list[str] = []

    class BlockingPipeline:
        def __init__(self, shared: SharedState) -> None:
            self.shared = shared

        def process(self, job_id: str) -> None:
            with self.shared.lock:
                self.shared.active += 1
                self.shared.max_active = max(
                    self.shared.max_active,
                    self.shared.active,
                )
                self.shared.started.append(job_id)
                if len(self.shared.started) == 2:
                    self.shared.both_started.set()

            self.shared.release.wait(2)

            with self.shared.lock:
                self.shared.active -= 1

    async def scenario() -> int:
        shared = SharedState()
        runner = runner_module.LocalTaskRunner(
            pipeline_factory=lambda: BlockingPipeline(shared),
            max_pending_jobs=2,
            worker_count=2,
        )
        await runner.start()
        await runner.enqueue("first")
        await runner.enqueue("second")
        both_started = await asyncio.to_thread(
            shared.both_started.wait,
            2,
        )
        shared.release.set()
        await runner.stop()
        assert both_started
        return shared.max_active

    assert asyncio.run(scenario()) == 2


def test_runner_hot_resizes_workers_without_restart() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    async def scenario() -> None:
        runner = runner_module.LocalTaskRunner(
            Pipeline(),
            pipeline_factory=Pipeline,
            worker_count=1,
        )
        await runner.start()
        assert runner.active_worker_count == 1

        await runner.resize_workers(4)
        await asyncio.sleep(0)
        assert runner.worker_count == 4
        assert runner.active_worker_count == 4
        assert runner.snapshot()["alive_workers"] == 4

        await runner.resize_workers(1)
        await asyncio.sleep(0.6)
        assert runner.worker_count == 1
        assert runner.active_worker_count == 1
        assert runner.snapshot()["alive_workers"] == 1
        await runner.stop()

    asyncio.run(scenario())


def test_runner_finishes_active_job_when_hot_shrinking() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class SharedState:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.started_count = 0
            self.both_started = threading.Event()
            self.release = threading.Event()
            self.completed_count = 0

    class BlockingPipeline:
        def __init__(self, shared: SharedState) -> None:
            self.shared = shared

        def process(self, job_id: str) -> None:
            with self.shared.lock:
                self.shared.started_count += 1
                if self.shared.started_count == 2:
                    self.shared.both_started.set()
            self.shared.release.wait(2)
            with self.shared.lock:
                self.shared.completed_count += 1

    async def scenario() -> int:
        shared = SharedState()
        runner = runner_module.LocalTaskRunner(
            pipeline_factory=lambda: BlockingPipeline(shared),
            worker_count=2,
        )
        await runner.start()
        await runner.enqueue("active-on-worker-zero")
        await runner.enqueue("active-on-worker-one")
        assert await asyncio.to_thread(shared.both_started.wait, 2)

        await runner.resize_workers(1)
        shared.release.set()
        await runner.stop()
        return shared.completed_count

    assert asyncio.run(scenario()) == 2


def test_runner_accepts_jobs_into_an_unbounded_fifo_queue() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    async def scenario() -> list[str]:
        runner = runner_module.LocalTaskRunner(
            Pipeline(),
            max_pending_jobs=1,
        )
        await runner.enqueue("first")
        await runner.enqueue("second")
        first = runner.queue.get_nowait()
        runner.queue.task_done()
        second = runner.queue.get_nowait()
        runner.queue.task_done()
        return [first, second]

    assert asyncio.run(scenario()) == ["first", "second"]


def test_runner_reservation_api_remains_compatible() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    async def scenario() -> None:
        runner = runner_module.LocalTaskRunner(
            Pipeline(),
            max_pending_jobs=1,
        )
        reservation = runner.reserve()
        assert runner.can_accept

        reservation.release()
        assert runner.can_accept

        replacement = runner.reserve()
        await replacement.enqueue("first")
        assert runner.queue.qsize() == 1
        assert runner.can_accept

    asyncio.run(scenario())


def test_runner_cancels_a_queued_job_and_releases_capacity() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    async def scenario() -> None:
        runner = runner_module.LocalTaskRunner(
            Pipeline(),
            max_pending_jobs=2,
        )
        await runner.enqueue("first")
        await runner.enqueue("second")

        assert await runner.cancel("first")
        assert runner.can_accept
        assert not await runner.cancel("missing")

        await runner.enqueue("third")
        assert runner.queue.get_nowait() == "second"
        runner.queue.task_done()
        assert runner.queue.get_nowait() == "third"
        runner.queue.task_done()

    asyncio.run(scenario())


def test_runner_snapshot_reports_heartbeat_and_active_jobs() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class BlockingPipeline:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def process(self, job_id: str) -> None:
            self.started.set()
            self.release.wait(2)

    async def scenario() -> tuple[dict, dict]:
        pipeline = BlockingPipeline()
        runner = runner_module.LocalTaskRunner(
            pipeline,
            heartbeat_interval_seconds=0.01,
        )
        await runner.start()
        started_snapshot = runner.snapshot()
        await runner.enqueue("job-1")
        assert await asyncio.to_thread(pipeline.started.wait, 1)
        await asyncio.sleep(0.03)
        busy_snapshot = runner.snapshot()
        pipeline.release.set()
        await runner.stop()
        return started_snapshot, busy_snapshot

    started_snapshot, busy_snapshot = asyncio.run(scenario())

    assert started_snapshot["healthy"] is True
    assert started_snapshot["worker_count"] == 1
    assert started_snapshot["alive_workers"] == 1
    assert started_snapshot["active_jobs"] == []
    assert datetime.fromisoformat(started_snapshot["last_heartbeat_at"])

    assert busy_snapshot["healthy"] is True
    assert busy_snapshot["active_jobs"] == [
        {
            "worker_index": 0,
            "job_id": "job-1",
            "started_at": busy_snapshot["active_jobs"][0]["started_at"],
        }
    ]
    assert busy_snapshot["queued_in_memory"] == 0
