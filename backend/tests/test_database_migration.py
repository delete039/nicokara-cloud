from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from app.core.database import Database


def test_initialize_adds_phase3_columns_to_phase2_database(tmp_path: Path) -> None:
    database_path = tmp_path / "phase2.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL,
                original_video_name TEXT NOT NULL,
                video_size_bytes INTEGER NOT NULL,
                video_sha256 TEXT NOT NULL,
                video_path TEXT NOT NULL,
                lyrics_source TEXT,
                lyrics_path TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    database = Database(database_path)
    database.initialize()

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
    assert "audio_path" in columns
    assert "transcript_path" in columns
    assert "lyrics_processed_path" in columns
    assert "timeline_path" in columns
    assert "ass_path" in columns
    assert "output_path" in columns


def test_job_state_changes_emit_structured_log_events(
    tmp_path: Path,
    caplog,
) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id="job-1",
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )

    with caplog.at_level(logging.INFO, logger="app.core.database"):
        database.update_job_state(
            "job-1",
            status="PROCESSING",
            stage="TRANSCRIBING",
            progress=40,
        )

    event = json.loads(caplog.records[-1].message)
    assert event == {
        "event": "job_state_changed",
        "job_id": "job-1",
        "status": "PROCESSING",
        "stage": "TRANSCRIBING",
        "progress": 40,
        "error_code": None,
    }


def test_job_lifecycle_is_saved_as_queryable_event_logs(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "job-logs"
    job_dir.mkdir()
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id="job-logs",
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        client_key="private-client-key",
        lyrics_source="text",
        lyrics_path=None,
    )
    database.update_job_state(
        "job-logs",
        status="FAILED",
        stage="TRANSCRIBING",
        progress=40,
        error_code="TRANSCRIPTION_FAILED",
        error_message="Raw internal exception must not be stored in logs.",
    )

    result = database.list_event_logs(
        level="ERROR",
        category="task",
        reference_id="job-logs",
        query="TRANSCRIPTION_FAILED",
        limit=20,
        offset=0,
    )

    assert result["total"] == 1
    assert result["items"][0]["event"] == "job.state_changed"
    assert result["items"][0]["details"]["stage"] == "TRANSCRIBING"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private-client-key" not in serialized
    assert "Raw internal exception" not in serialized


def test_upload_lifecycle_is_saved_as_event_logs(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    ticket_id = "upload-ticket-1"
    database.create_upload_ticket(
        ticket_id=ticket_id,
        client_key="private-client-key",
        video_name="song.mp4",
        video_size_bytes=1024,
    )
    database.activate_upload_tickets(max_active_uploads=1)
    database.begin_upload_ticket(ticket_id)
    assert database.complete_upload_ticket(ticket_id, "job-1") is True

    result = database.list_event_logs(
        reference_id=ticket_id,
        limit=20,
        offset=0,
    )

    assert [item["event"] for item in result["items"]] == [
        "upload.completed",
        "upload.started",
        "upload.ready",
        "upload.queued",
    ]
    assert all(item["category"] == "upload" for item in result["items"])
