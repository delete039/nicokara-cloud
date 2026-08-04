from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
from pathlib import Path
import threading

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app


def create_database_job(
    database: Database,
    storage_dir: Path,
    job_id: str,
) -> Path:
    job_dir = storage_dir / job_id
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )
    return job_dir


def test_api_responses_include_browser_security_headers(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )


def test_queue_backpressure_rejects_upload_before_writing_files(
    tmp_path: Path,
) -> None:
    class FullRunner:
        can_accept = False

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings, runner=FullRunner())) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )

    assert response.status_code == 503
    assert list(settings.storage_dir.iterdir()) == []


def test_cleanup_deletes_only_expired_terminal_jobs(tmp_path: Path) -> None:
    from app.tasks.cleanup import JobCleanupService

    database = Database(tmp_path / "data" / "jobs.sqlite3")
    database.path.parent.mkdir(parents=True)
    database.initialize()
    storage_dir = tmp_path / "jobs"
    completed_dir = create_database_job(
        database,
        storage_dir,
        "00000000-0000-0000-0000-000000000001",
    )
    active_dir = create_database_job(
        database,
        storage_dir,
        "00000000-0000-0000-0000-000000000002",
    )
    database.update_job_state(
        completed_dir.name,
        status="COMPLETED",
        stage="VIDEO_RENDERING_COMPLETE",
        progress=100,
    )
    database.update_job_state(
        active_dir.name,
        status="PROCESSING",
        stage="TRANSCRIBING",
        progress=40,
    )
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE jobs SET updated_at = ?", (old,))

    deleted = JobCleanupService(
        database=database,
        storage_dir=storage_dir,
        retention_hours=24,
    ).run_once()

    assert deleted == [completed_dir.name]
    assert not completed_dir.exists()
    assert database.get_job(completed_dir.name) is None
    assert active_dir.exists()
    assert database.get_job(active_dir.name) is not None


def test_restart_marks_interrupted_jobs_failed_and_requeues_uploads(
    tmp_path: Path,
) -> None:
    class RecordingRunner:
        can_accept = True

        def __init__(self) -> None:
            self.job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    uploaded_id = "00000000-0000-0000-0000-000000000003"
    interrupted_id = "00000000-0000-0000-0000-000000000004"
    create_database_job(database, settings.storage_dir, uploaded_id)
    create_database_job(database, settings.storage_dir, interrupted_id)
    database.update_job_state(
        interrupted_id,
        status="PROCESSING",
        stage="RENDERING_VIDEO",
        progress=98,
    )

    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)):
        pass

    assert runner.job_ids == [uploaded_id]
    interrupted = database.get_job(interrupted_id)
    assert interrupted is not None
    assert interrupted["status"] == "FAILED"
    assert interrupted["error_code"] == "SERVICE_RESTARTED"


def test_restart_eventually_requeues_every_uploaded_job(
    tmp_path: Path,
) -> None:
    from app.tasks.runner import LocalTaskRunner

    class RecordingPipeline:
        def __init__(self) -> None:
            self.job_ids: list[str] = []
            self.completed = threading.Event()

        def process(self, job_id: str) -> None:
            self.job_ids.append(job_id)
            if len(self.job_ids) == 3:
                self.completed.set()

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    job_ids = [
        f"00000000-0000-0000-0000-{index:012d}"
        for index in range(10, 13)
    ]
    for job_id in job_ids:
        create_database_job(database, settings.storage_dir, job_id)

    pipeline = RecordingPipeline()
    runner = LocalTaskRunner(pipeline, max_pending_jobs=1)
    with TestClient(create_app(settings, runner=runner)):
        assert pipeline.completed.wait(2)

    assert pipeline.job_ids == job_ids


def test_upload_uses_atomic_runner_reservation(tmp_path: Path) -> None:
    class Reservation:
        def __init__(self, runner) -> None:
            self.runner = runner

        async def enqueue(self, job_id: str) -> None:
            self.runner.job_ids.append(job_id)

        def release(self) -> None:
            pass

    class ReservingRunner:
        can_accept = False

        def __init__(self) -> None:
            self.job_ids: list[str] = []
            self.reservations = 0

        def reserve(self) -> Reservation:
            self.reservations += 1
            return Reservation(self)

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    runner = ReservingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )

    assert response.status_code == 201
    assert runner.reservations == 1
    assert runner.job_ids == [response.json()["id"]]


def test_rejected_upload_releases_reserved_queue_capacity(
    tmp_path: Path,
) -> None:
    from app.tasks.runner import LocalTaskRunner

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    runner = LocalTaskRunner(Pipeline(), max_pending_jobs=1)
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.txt",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )
        assert runner.can_accept

    assert response.status_code == 415


def test_job_response_reports_queue_position_and_size(tmp_path: Path) -> None:
    class PassiveRunner:
        can_accept = True

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    upload = {
        "video": (
            "song.mp4",
            b"\x00\x00\x00\x18ftypisomvideo",
            "video/mp4",
        )
    }
    with TestClient(create_app(settings, runner=PassiveRunner())) as client:
        first = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "一"},
        )
        second = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "二"},
        )
        refreshed_first = client.get(
            f"/api/v1/jobs/{first.json()['id']}"
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["queue_position"] == 2
    assert second.json()["queue_size"] == 2
    assert refreshed_first.json()["queue_position"] == 1
    assert refreshed_first.json()["queue_size"] == 2


def test_canceling_a_queued_job_updates_the_remaining_queue(
    tmp_path: Path,
) -> None:
    class CancellableRunner:
        can_accept = True

        def __init__(self) -> None:
            self.canceled_job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            pass

        async def cancel(self, job_id: str) -> bool:
            self.canceled_job_ids.append(job_id)
            return True

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    runner = CancellableRunner()
    upload = {
        "video": (
            "song.mp4",
            b"\x00\x00\x00\x18ftypisomvideo",
            "video/mp4",
        )
    }
    with TestClient(create_app(settings, runner=runner)) as client:
        first = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "一"},
        )
        second = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "二"},
        )

        canceled = client.post(
            f"/api/v1/jobs/{first.json()['id']}/cancel"
        )
        refreshed_second = client.get(
            f"/api/v1/jobs/{second.json()['id']}"
        )

    assert canceled.status_code == 200
    assert canceled.json()["status"] == "CANCELED"
    assert canceled.json()["stage"] == "CANCELED_BY_USER"
    assert canceled.json()["queue_position"] is None
    assert runner.canceled_job_ids == [first.json()["id"]]
    assert refreshed_second.json()["queue_position"] == 1
    assert refreshed_second.json()["queue_size"] == 1


def test_persisted_backlog_has_priority_over_new_uploads(
    tmp_path: Path,
) -> None:
    class PassiveRunner:
        can_accept = True

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
        max_pending_jobs=2,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    for index in range(20, 22):
        create_database_job(
            database,
            settings.storage_dir,
            f"00000000-0000-0000-0000-{index:012d}",
        )

    with TestClient(create_app(settings, runner=PassiveRunner())) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "新任务"},
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"


def test_startup_cleanup_removes_expired_completed_job(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=True,
        job_retention_hours=24,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    job_id = "00000000-0000-0000-0000-000000000005"
    job_dir = create_database_job(database, settings.storage_dir, job_id)
    database.update_job_state(
        job_id,
        status="COMPLETED",
        stage="VIDEO_RENDERING_COMPLETE",
        progress=100,
    )
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (old, job_id),
        )

    with TestClient(create_app(settings)):
        pass

    assert not job_dir.exists()
    assert database.get_job(job_id) is None


def test_sqlite_uses_wal_busy_timeout_and_status_index(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()

    with database.connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 5000
    assert "idx_jobs_status_updated" in indexes


def test_download_rejects_database_path_outside_job_directory(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )
        job_id = response.json()["id"]
        outside = tmp_path / "outside.json"
        outside.write_text('{"secret": true}', encoding="utf-8")
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET transcript_path = ? WHERE id = ?",
                (str(outside), job_id),
            )

        download = client.get(f"/api/v1/jobs/{job_id}/transcript")

    assert download.status_code == 410


def test_periodic_cleanup_runs_while_service_is_alive() -> None:
    from app.tasks.cleanup import PeriodicCleanupRunner

    class RecordingCleanup:
        def __init__(self) -> None:
            self.calls = 0
            self.called = threading.Event()

        def run_once(self) -> list[str]:
            self.calls += 1
            self.called.set()
            return []

    async def scenario() -> int:
        cleanup = RecordingCleanup()
        runner = PeriodicCleanupRunner(
            cleanup,
            interval_seconds=0.01,
        )
        await runner.start()
        completed = await asyncio.to_thread(cleanup.called.wait, 1)
        await runner.stop()
        assert completed
        return cleanup.calls

    assert asyncio.run(scenario()) >= 1


def test_upload_rate_limiter_blocks_repeated_requests() -> None:
    from app.core.rate_limit import UploadRateLimiter

    limiter = UploadRateLimiter(
        max_requests=2,
        window_seconds=60,
    )

    assert limiter.allow("127.0.0.1", now=100)
    assert limiter.allow("127.0.0.1", now=101)
    assert not limiter.allow("127.0.0.1", now=102)
    assert limiter.allow("127.0.0.1", now=161)


def test_api_rate_limits_upload_creation(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        max_uploads_per_hour=1,
    )
    upload = {
        "video": (
            "song.mp4",
            b"\x00\x00\x00\x18ftypisomvideo",
            "video/mp4",
        )
    }

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "歌詞"},
        )
        second = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "歌詞"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.headers["retry-after"]
