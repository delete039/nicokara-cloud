from __future__ import annotations

import importlib
import importlib.util
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.tasks.runner import LocalTaskRunner
from app.tasks.cleanup import JobCleanupService


def load_event_logging_module():
    spec = importlib.util.find_spec("app.core.event_logging")
    assert spec is not None, "统一结构化日志模块尚未实现"
    return importlib.import_module("app.core.event_logging")


def test_settings_expose_safe_production_logging_defaults(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, storage_dir=tmp_path / "jobs")

    assert settings.log_level == "INFO"
    assert settings.event_log_level == "INFO"
    assert settings.json_console_logs is False
    assert settings.event_log_debug is False
    assert settings.event_log_retention_days > 0
    assert settings.event_log_max_rows > 0


def test_event_log_schema_migrates_existing_sqlite_and_supports_filters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                reference_type TEXT,
                reference_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO event_logs (
                level, category, event, message, reference_type,
                reference_id, details, created_at
            ) VALUES ('INFO', 'task', 'legacy.event', '旧日志', 'job',
                      'job-legacy', '{}', '2026-08-17T00:00:00+00:00')
            """
        )

    database = Database(path)
    database.initialize()
    database.record_event_log(
        level="WARNING",
        category="pipeline",
        event="stage.fallback",
        message="高精度对齐不可用，切换普通对齐器",
        reference_type="job",
        reference_id="job-1",
        run_id="run-2",
        stage="ALIGNING",
        component="fa_kara",
        request_id="request-1",
        duration_ms=125.5,
        schema_version=1,
        details={"reason": "model unavailable"},
    )

    result = database.list_event_logs(
        level="WARNING",
        event="stage.fallback",
        component="fa_kara",
        stage="ALIGNING",
        reference_id="job-1",
        run_id="run-2",
        request_id="request-1",
        order="asc",
    )

    assert result["total"] == 1
    item = result["items"][0]
    assert item["run_id"] == "run-2"
    assert item["stage"] == "ALIGNING"
    assert item["component"] == "fa_kara"
    assert item["duration_ms"] == pytest.approx(125.5)
    assert item["schema_version"] == 1

    legacy = database.list_event_logs(event="legacy.event")["items"][0]
    assert legacy["schema_version"] == 1
    assert legacy["run_id"] is None


def test_structured_logger_redacts_secrets_paths_and_long_diagnostics(
    tmp_path: Path,
) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    recorder = event_logging.StructuredEventLogger(
        database=database,
        event_log_level="DEBUG",
        debug_enabled=True,
    )

    recorder.emit(
        event="external.failed",
        level="ERROR",
        category="external",
        message="外部调用失败",
        reference_type="job",
        reference_id="job-1",
        component="deepseek",
        details={
            "api_key": "sk-very-secret",
            "Authorization": "Bearer admin-secret",
            "cookie": "session=secret",
            "url": "https://example.test/run?token=url-secret&x=1",
            "input_path": str(tmp_path / "private" / "song.mp4"),
            "command": [
                "ffmpeg",
                "-headers",
                "Authorization: Bearer command-secret",
                "-i",
                str(tmp_path / "private" / "song.mp4"),
            ],
            "stderr_tail": "x" * 20_000,
        },
    )

    text = str(database.list_event_logs(event="external.failed"))
    assert "very-secret" not in text
    assert "admin-secret" not in text
    assert "url-secret" not in text
    assert "command-secret" not in text
    assert str(tmp_path) not in text
    assert "[REDACTED]" in text
    assert len(text) < 15_000


def test_debug_gate_progress_throttle_and_write_failure_are_non_fatal(
    tmp_path: Path,
) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    recorder = event_logging.StructuredEventLogger(
        database=database,
        event_log_level="INFO",
        debug_enabled=False,
        progress_throttle_seconds=60,
    )

    assert recorder.emit(
        event="stage.debug",
        level="DEBUG",
        category="pipeline",
        message="调试详情",
    ) is False
    assert recorder.progress(
        event="stage.progress",
        category="pipeline",
        message="处理中",
        reference_id="job-1",
        run_id="run-1",
        stage="TRANSCRIBING",
        progress=10,
    ) is True
    assert recorder.progress(
        event="stage.progress",
        category="pipeline",
        message="处理中",
        reference_id="job-1",
        run_id="run-1",
        stage="TRANSCRIBING",
        progress=11,
    ) is False
    assert database.list_event_logs(event="stage.progress")["total"] == 1

    database._insert_event_log = lambda **_: (_ for _ in ()).throw(
        sqlite3.OperationalError("database is locked")
    )
    assert recorder.emit(
        event="pipeline.completed",
        level="INFO",
        category="pipeline",
        message="处理完成",
    ) is False


def test_console_and_database_log_thresholds_are_independent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    console_logger = logging.getLogger("tests.nicokara.event-thresholds")
    caplog.set_level(logging.INFO, logger=console_logger.name)
    recorder = event_logging.StructuredEventLogger(
        database=database,
        event_log_level="ERROR",
        console_level="INFO",
        console_logger=console_logger,
    )

    assert recorder.emit(
        event="pipeline.started",
        level="INFO",
        category="pipeline",
        message="流水线开始",
    ) is True

    assert database.list_event_logs(event="pipeline.started")["total"] == 0
    assert any("pipeline.started" in record.getMessage() for record in caplog.records)


def test_event_log_database_failure_does_not_emit_exception_traceback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    console_logger = logging.getLogger("tests.nicokara.event-write-failure")
    caplog.set_level(logging.ERROR, logger=console_logger.name)
    recorder = event_logging.StructuredEventLogger(
        database=database,
        console_logger=console_logger,
    )
    database._insert_event_log = lambda **_: (_ for _ in ()).throw(
        sqlite3.OperationalError("database is locked")
    )

    assert recorder.emit(
        event="pipeline.completed",
        level="INFO",
        category="pipeline",
        message="处理完成",
    ) is False

    failures = [
        record for record in caplog.records
        if "Event log persistence failed" in record.getMessage()
    ]
    assert len(failures) == 1
    assert failures[0].exc_info is None


def test_event_log_cleanup_honors_age_and_max_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    recent = datetime.now(UTC).isoformat()
    with database.connect() as connection:
        for index, created_at in enumerate([old, recent, recent, recent]):
            connection.execute(
                """
                INSERT INTO event_logs (
                    level, category, event, message, details, created_at
                ) VALUES ('INFO', 'test', ?, ?, '{}', ?)
                """,
                (f"event.{index}", f"日志 {index}", created_at),
            )

    deleted = database.cleanup_event_logs(
        older_than=(datetime.now(UTC) - timedelta(days=7)).isoformat(),
        max_rows=2,
    )

    assert deleted == 2
    remaining = database.list_event_logs(order="asc", limit=10)
    assert remaining["total"] == 2
    assert [item["event"] for item in remaining["items"]] == [
        "event.2",
        "event.3",
    ]


def test_stage_trace_records_success_failure_and_duration(tmp_path: Path) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    recorder = event_logging.StructuredEventLogger(database=database)

    with recorder.stage(
        job_id="job-1",
        run_id="run-1",
        stage="TRANSCRIBING",
        component="whisper",
        message="歌声时间分析",
        details={"model": "small"},
    ) as trace:
        trace.result(language="ja", segment_count=3)

    with pytest.raises(RuntimeError):
        with recorder.stage(
            job_id="job-1",
            run_id="run-1",
            stage="ALIGNING",
            component="fa_kara",
            message="歌词对齐",
        ):
            raise RuntimeError("alignment token=private-value failed")

    events = database.list_event_logs(reference_id="job-1", order="asc")["items"]
    assert [item["event"] for item in events] == [
        "stage.started",
        "stage.completed",
        "stage.started",
        "stage.failed",
    ]
    assert events[1]["duration_ms"] >= 0
    assert events[1]["details"]["segment_count"] == 3
    assert events[3]["details"]["exception_type"] == "RuntimeError"
    assert "private-value" not in str(events[3]["details"])


def test_runner_assigns_distinct_run_ids_and_records_queue_wait(tmp_path: Path) -> None:
    event_logging = load_event_logging_module()
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    recorder = event_logging.StructuredEventLogger(database=database)

    class Pipeline:
        def process(self, job_id: str) -> None:
            recorder.emit(
                event="pipeline.started",
                level="INFO",
                category="pipeline",
                message="流水线启动",
                job_id=job_id,
            )

    async def scenario() -> None:
        runner = LocalTaskRunner(Pipeline(), event_logger=recorder)
        await runner.start()
        await runner.enqueue("same-job")
        await runner.enqueue("same-job")
        await runner.stop()

    import asyncio

    asyncio.run(scenario())
    events = database.list_event_logs(reference_id="same-job", order="asc", limit=20)[
        "items"
    ]
    assigned = [item for item in events if item["event"] == "worker.assigned"]
    pipeline = [item for item in events if item["event"] == "pipeline.started"]
    assert len(assigned) == 2
    assert len({item["run_id"] for item in assigned}) == 2
    assert [item["run_id"] for item in pipeline] == [
        item["run_id"] for item in assigned
    ]
    assert all(item["details"]["queue_wait_ms"] >= 0 for item in assigned)


def test_request_id_header_and_request_events_skip_health_polling(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/jobs/not-found")
        request_id = response.headers.get("X-Request-ID")
        health = client.get("/api/v1/health")
        upload_poll = client.get(
            "/api/v1/upload-tickets/10000000-0000-0000-0000-000000000001"
        )
        database = client.app.state.database
        request_events = database.list_event_logs(
            category="request", request_id=request_id, order="asc"
        )["items"]

    assert request_id
    assert health.headers.get("X-Request-ID")
    assert upload_poll.headers.get("X-Request-ID")
    assert [item["event"] for item in request_events] == [
        "request.started",
        "request.completed",
    ]
    assert request_events[1]["details"]["method"] == "GET"
    assert request_events[1]["details"]["status_code"] == 404
    all_request_events = database.list_event_logs(category="request", limit=20)["items"]
    assert not any(item["details"].get("route") == "/api/v1/health" for item in all_request_events)
    assert not any(
        item["details"].get("route", "").startswith(
            "/api/v1/upload-tickets/"
        )
        for item in all_request_events
    )


def test_periodic_cleanup_applies_event_log_retention(tmp_path: Path) -> None:
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO event_logs (
                level, category, event, message, details, created_at
            ) VALUES ('INFO', 'system', 'old.event', '旧日志', '{}', ?)
            """,
            ((datetime.now(UTC) - timedelta(days=3)).isoformat(),),
        )
    service = JobCleanupService(
        database=database,
        storage_dir=tmp_path / "jobs",
        retention_hours=24,
        event_log_retention_days=1,
        event_log_max_rows=100,
    )

    service.run_once(now=datetime.now(UTC))

    assert database.list_event_logs(event="old.event")["total"] == 0


def test_periodic_cleanup_keeps_event_log_at_or_below_max_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    for index in range(4):
        database.record_event_log(
            level="INFO",
            category="test",
            event=f"recent.{index}",
            message=f"近期日志 {index}",
        )
    service = JobCleanupService(
        database=database,
        storage_dir=tmp_path / "jobs",
        retention_hours=24,
        event_log_retention_days=30,
        event_log_max_rows=2,
    )

    service.run_once(now=datetime.now(UTC))

    assert database.list_event_logs(limit=20)["total"] <= 2


def test_service_restart_logs_interrupted_stage_and_review_recovery(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "events.sqlite3")
    database.initialize()
    recorder = load_event_logging_module().StructuredEventLogger(database=database)
    database.configure_event_logger(recorder)
    for job_id, status, stage in [
        ("job-processing", "PROCESSING", "TRANSCRIBING"),
        ("job-review", "LYRICS_PROCESSED", "READING_REVIEW_SAVING"),
    ]:
        job_dir = tmp_path / job_id
        job_dir.mkdir()
        video = job_dir / "input.mp4"
        video.write_bytes(b"video")
        database.create_job(
            job_id=job_id,
            original_video_name="song.mp4",
            video_size_bytes=5,
            video_sha256="sha",
            video_path=video,
            lyrics_source="text",
            lyrics_path=None,
        )
        with database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, stage = ? WHERE id = ?",
                (status, stage, job_id),
            )

    database.recover_interrupted_jobs()

    interrupted = database.list_event_logs(
        reference_id="job-processing", event="job.interrupted"
    )["items"][0]
    assert interrupted["stage"] == "TRANSCRIBING"
    assert interrupted["component"] == "service_recovery"
    recovered = database.list_event_logs(
        reference_id="job-review", event="job.reading_review_recovered"
    )["items"][0]
    assert recovered["details"]["restored_stage"] == "READING_REVIEW_REQUIRED"
