from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    original_video_name TEXT NOT NULL,
    video_size_bytes INTEGER NOT NULL,
    video_sha256 TEXT NOT NULL,
    video_path TEXT NOT NULL,
    client_key TEXT,
    lyrics_source TEXT,
    lyrics_path TEXT,
    vocal_mode TEXT NOT NULL DEFAULT 'on',
    audio_path TEXT,
    transcript_path TEXT,
    lyrics_processed_path TEXT,
    timeline_path TEXT,
    ass_path TEXT,
    output_path TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS upload_rate_limits (
    client_key TEXT NOT NULL,
    requested_at REAL NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobCanceledError(RuntimeError):
    """Raised when processing tries to update a canceled job."""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name in (
                "vocal_mode",
                "client_key",
                "audio_path",
                "transcript_path",
                "lyrics_processed_path",
                "timeline_path",
                "ass_path",
                "output_path",
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_updated
                ON jobs(status, updated_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_client_status
                ON jobs(client_key, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_upload_rate_limits_key_time
                ON upload_rate_limits(client_key, requested_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_upload_rate_limits_time
                ON upload_rate_limits(requested_at)
                """
            )

    def consume_upload_limit(
        self,
        client_key: str,
        *,
        max_requests: int,
        window_seconds: int,
        now: float,
    ) -> tuple[bool, int]:
        cutoff = now - window_seconds
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM upload_rate_limits WHERE requested_at <= ?",
                (cutoff,),
            )
            rows = connection.execute(
                """
                SELECT requested_at
                FROM upload_rate_limits
                WHERE client_key = ?
                ORDER BY requested_at ASC
                """,
                (client_key,),
            ).fetchall()
            if len(rows) >= max_requests:
                retry_after = max(
                    1,
                    math.ceil(rows[0]["requested_at"] + window_seconds - now),
                )
                return False, retry_after
            connection.execute(
                """
                INSERT INTO upload_rate_limits (client_key, requested_at)
                VALUES (?, ?)
                """,
                (client_key, now),
            )
        return True, 0

    def create_job(
        self,
        *,
        job_id: str,
        original_video_name: str,
        video_size_bytes: int,
        video_sha256: str,
        video_path: Path,
        client_key: str | None = None,
        lyrics_source: str | None,
        lyrics_path: Path | None,
        vocal_mode: str = "on",
    ) -> dict:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, stage, progress, original_video_name,
                    video_size_bytes, video_sha256, video_path,
                    client_key, lyrics_source, lyrics_path, vocal_mode,
                    created_at, updated_at
                )
                VALUES (?, 'UPLOADED', 'UPLOAD_COMPLETE', 100,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    original_video_name,
                    video_size_bytes,
                    video_sha256,
                    str(video_path),
                    client_key,
                    lyrics_source,
                    str(lyrics_path) if lyrics_path else None,
                    vocal_mode,
                    timestamp,
                    timestamp,
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("Created job could not be read back")
        return job

    def count_active_jobs_for_client(self, client_key: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM jobs
                WHERE client_key = ?
                  AND status IN ('UPLOADED', 'PROCESSING')
                """,
                (client_key,),
            ).fetchone()
        return int(row[0])

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_job_state(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        progress: int,
        audio_path: Path | None = None,
        transcript_path: Path | None = None,
        lyrics_processed_path: Path | None = None,
        timeline_path: Path | None = None,
        ass_path: Path | None = None,
        output_path: Path | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        assignments = [
            "status = ?",
            "stage = ?",
            "progress = ?",
            "error_code = ?",
            "error_message = ?",
            "updated_at = ?",
        ]
        values: list[object] = [
            status,
            stage,
            progress,
            error_code,
            error_message,
            utc_now(),
        ]
        if audio_path is not None:
            assignments.append("audio_path = ?")
            values.append(str(audio_path))
        if transcript_path is not None:
            assignments.append("transcript_path = ?")
            values.append(str(transcript_path))
        if lyrics_processed_path is not None:
            assignments.append("lyrics_processed_path = ?")
            values.append(str(lyrics_processed_path))
        if timeline_path is not None:
            assignments.append("timeline_path = ?")
            values.append(str(timeline_path))
        if ass_path is not None:
            assignments.append("ass_path = ?")
            values.append(str(ass_path))
        if output_path is not None:
            assignments.append("output_path = ?")
            values.append(str(output_path))
        values.append(job_id)

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET {', '.join(assignments)}
                WHERE id = ? AND status != 'CANCELED'
                """,
                values,
            )
            if cursor.rowcount != 1:
                current = connection.execute(
                    "SELECT status FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(f"Job not found: {job_id}")
                if current["status"] == "CANCELED":
                    raise JobCanceledError(f"Job was canceled: {job_id}")
                raise RuntimeError(f"Job state was not updated: {job_id}")

    def cancel_job(self, job_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'CANCELED',
                    stage = 'CANCELED_BY_USER',
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('UPLOADED', 'PROCESSING')
                """,
                (utc_now(), job_id),
            )
        return cursor.rowcount == 1

    def list_job_ids(self, *, status: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (status,),
            ).fetchall()
        return [row["id"] for row in rows]

    def count_jobs(self, *, status: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row[0])

    def queue_metrics(self, job_id: str) -> tuple[int | None, int | None]:
        with self.connect() as connection:
            job = connection.execute(
                "SELECT status, created_at FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if job is None or job["status"] != "UPLOADED":
                return None, None
            queue_size = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'UPLOADED'"
            ).fetchone()[0]
            queue_position = connection.execute(
                """
                SELECT COUNT(*)
                FROM jobs
                WHERE status = 'UPLOADED'
                  AND (
                    created_at < ?
                    OR (created_at = ? AND id <= ?)
                  )
                """,
                (job["created_at"], job["created_at"], job_id),
            ).fetchone()[0]
        return queue_position, queue_size

    def recover_interrupted_jobs(self) -> list[str]:
        timestamp = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = 'PROCESSING'"
            ).fetchall()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'FAILED',
                    error_code = 'SERVICE_RESTARTED',
                    error_message = ?,
                    updated_at = ?
                WHERE status = 'PROCESSING'
                """,
                (
                    "Processing was interrupted by a service restart. "
                    "Create a new task to retry.",
                    timestamp,
                ),
            )
        return [row["id"] for row in rows]

    def list_expired_terminal_job_ids(self, *, cutoff: str) -> list[str]:
        terminal_statuses = (
            "COMPLETED",
            "FAILED",
            "CANCELED",
            "TRANSCRIBED",
            "LYRICS_PROCESSED",
            "ALIGNED",
            "SUBTITLE_GENERATED",
        )
        placeholders = ", ".join("?" for _ in terminal_statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id FROM jobs
                WHERE status IN ({placeholders})
                  AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (*terminal_statuses, cutoff),
            ).fetchall()
        return [row["id"] for row in rows]

    def delete_job(self, job_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM jobs WHERE id = ?",
                (job_id,),
            )
