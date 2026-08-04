from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
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

CREATE TABLE IF NOT EXISTS upload_tickets (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    client_key TEXT NOT NULL,
    video_name TEXT NOT NULL,
    video_size_bytes INTEGER NOT NULL,
    job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
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
                CREATE INDEX IF NOT EXISTS idx_upload_tickets_status_created
                ON upload_tickets(status, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_upload_tickets_client_status
                ON upload_tickets(client_key, status)
                """
            )

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

    def count_active_upload_tickets_for_client(self, client_key: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM upload_tickets
                WHERE client_key = ?
                  AND status IN ('WAITING', 'READY', 'UPLOADING')
                """,
                (client_key,),
            ).fetchone()
        return int(row[0])

    def create_upload_ticket(
        self,
        *,
        ticket_id: str,
        client_key: str,
        video_name: str,
        video_size_bytes: int,
    ) -> dict:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO upload_tickets (
                    id, status, client_key, video_name, video_size_bytes,
                    created_at, updated_at, last_seen_at
                )
                VALUES (?, 'WAITING', ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    client_key,
                    video_name,
                    video_size_bytes,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        ticket = self.get_upload_ticket(ticket_id)
        if ticket is None:
            raise RuntimeError("Created upload ticket could not be read back")
        return ticket

    def get_upload_ticket(self, ticket_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM upload_tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
        return dict(row) if row else None

    def touch_upload_ticket(self, ticket_id: str) -> None:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE upload_tickets
                SET last_seen_at = ?, updated_at = ?
                WHERE id = ?
                  AND status IN ('WAITING', 'READY')
                """,
                (timestamp, timestamp, ticket_id),
            )

    def upload_ticket_metrics(
        self,
        ticket_id: str,
    ) -> tuple[int | None, int | None]:
        with self.connect() as connection:
            ticket = connection.execute(
                "SELECT status, created_at FROM upload_tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if ticket is None or ticket["status"] != "WAITING":
                return None, None
            queue_size = connection.execute(
                """
                SELECT COUNT(*)
                FROM upload_tickets
                WHERE status = 'WAITING'
                """
            ).fetchone()[0]
            queue_position = connection.execute(
                """
                SELECT COUNT(*)
                FROM upload_tickets
                WHERE status = 'WAITING'
                  AND (
                    created_at < ?
                    OR (created_at = ? AND id <= ?)
                  )
                """,
                (ticket["created_at"], ticket["created_at"], ticket_id),
            ).fetchone()[0]
        return queue_position, queue_size

    def activate_upload_tickets(self, *, max_active_uploads: int) -> list[str]:
        if max_active_uploads <= 0:
            return []
        timestamp = utc_now()
        activated: list[str] = []
        with self.connect() as connection:
            active_uploads = connection.execute(
                """
                SELECT COUNT(*)
                FROM upload_tickets
                WHERE status IN ('READY', 'UPLOADING')
                """
            ).fetchone()[0]
            available = max_active_uploads - int(active_uploads)
            if available <= 0:
                return []
            rows = connection.execute(
                """
                SELECT id
                FROM upload_tickets
                WHERE status = 'WAITING'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (available,),
            ).fetchall()
            for row in rows:
                cursor = connection.execute(
                    """
                    UPDATE upload_tickets
                    SET status = 'READY', updated_at = ?, last_seen_at = ?
                    WHERE id = ? AND status = 'WAITING'
                    """,
                    (timestamp, timestamp, row["id"]),
                )
                if cursor.rowcount == 1:
                    activated.append(row["id"])
        return activated

    def begin_upload_ticket(self, ticket_id: str) -> dict | None:
        timestamp = utc_now()
        upload_started = False
        with self.connect() as connection:
            ticket = connection.execute(
                "SELECT * FROM upload_tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if ticket is None:
                return None
            if ticket["status"] != "READY":
                result = dict(ticket)
                result["_upload_started"] = False
                return result
            cursor = connection.execute(
                """
                UPDATE upload_tickets
                SET status = 'UPLOADING', updated_at = ?, last_seen_at = ?
                WHERE id = ? AND status = 'READY'
                """,
                (timestamp, timestamp, ticket_id),
            )
            upload_started = cursor.rowcount == 1
        refreshed = self.get_upload_ticket(ticket_id)
        if refreshed is None:
            raise RuntimeError("Upload ticket disappeared")
        refreshed["_upload_started"] = upload_started
        return refreshed

    def complete_upload_ticket(self, ticket_id: str, job_id: str) -> bool:
        timestamp = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE upload_tickets
                SET status = 'COMPLETED',
                    job_id = ?,
                    updated_at = ?,
                    last_seen_at = ?
                WHERE id = ?
                  AND status = 'UPLOADING'
                """,
                (job_id, timestamp, timestamp, ticket_id),
            )
        return cursor.rowcount == 1

    def cancel_upload_ticket(self, ticket_id: str) -> bool:
        timestamp = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE upload_tickets
                SET status = 'CANCELED',
                    updated_at = ?,
                    last_seen_at = ?
                WHERE id = ?
                  AND status IN ('WAITING', 'READY', 'UPLOADING')
                """,
                (timestamp, timestamp, ticket_id),
            )
        return cursor.rowcount == 1

    def expire_stale_upload_tickets(
        self,
        *,
        waiting_cutoff: str,
        uploading_cutoff: str,
    ) -> list[str]:
        timestamp = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM upload_tickets
                WHERE (
                    status IN ('WAITING', 'READY')
                    AND last_seen_at < ?
                )
                   OR (
                    status = 'UPLOADING'
                    AND updated_at < ?
                )
                """,
                (waiting_cutoff, uploading_cutoff),
            ).fetchall()
            ticket_ids = [row["id"] for row in rows]
            if ticket_ids:
                placeholders = ", ".join("?" for _ in ticket_ids)
                connection.execute(
                    f"""
                    UPDATE upload_tickets
                    SET status = 'EXPIRED',
                        updated_at = ?,
                        last_seen_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (timestamp, timestamp, *ticket_ids),
                )
        return ticket_ids

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
