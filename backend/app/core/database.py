from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


logger = logging.getLogger(__name__)

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
    client_submission_id TEXT,
    input_mode TEXT NOT NULL DEFAULT 'VIDEO',
    source_upload_size_bytes INTEGER,
    source_upload_sha256 TEXT,
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
    client_submission_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    reference_type TEXT,
    reference_id TEXT,
    run_id TEXT,
    stage TEXT,
    component TEXT,
    duration_ms REAL,
    request_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    details TEXT,
    created_at TEXT NOT NULL
);

"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobCanceledError(RuntimeError):
    """Raised when processing tries to update a canceled job."""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.event_logger: Any | None = None

    def configure_event_logger(self, event_logger: Any) -> None:
        self.event_logger = event_logger

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
                "client_submission_id",
                "input_mode",
                "source_upload_size_bytes",
                "source_upload_sha256",
            ):
                if name not in columns:
                    definition = (
                        "TEXT NOT NULL DEFAULT 'VIDEO'"
                        if name == "input_mode"
                        else "INTEGER"
                        if name == "source_upload_size_bytes"
                        else "TEXT"
                    )
                    connection.execute(
                        f"ALTER TABLE jobs ADD COLUMN {name} {definition}"
                    )
            upload_ticket_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(upload_tickets)"
                ).fetchall()
            }
            if "client_submission_id" not in upload_ticket_columns:
                connection.execute(
                    "ALTER TABLE upload_tickets ADD COLUMN client_submission_id TEXT"
                )
            event_log_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(event_logs)"
                ).fetchall()
            }
            for name, definition in {
                "run_id": "TEXT",
                "stage": "TEXT",
                "component": "TEXT",
                "duration_ms": "REAL",
                "request_id": "TEXT",
                "schema_version": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                if name not in event_log_columns:
                    connection.execute(
                        f"ALTER TABLE event_logs ADD COLUMN {name} {definition}"
                    )
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
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_submission_id
                ON jobs(client_submission_id)
                WHERE client_submission_id IS NOT NULL
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_audit_created
                ON admin_audit_events(created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_logs_created
                ON event_logs(created_at DESC, id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_logs_filters
                ON event_logs(level, category, reference_id, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_logs_job_timeline
                ON event_logs(reference_id, run_id, created_at, id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_logs_event_stage_component
                ON event_logs(event, stage, component, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_logs_request
                ON event_logs(request_id, created_at DESC)
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
        client_submission_id: str | None = None,
        input_mode: str = "VIDEO",
        source_upload_size_bytes: int | None = None,
        source_upload_sha256: str | None = None,
    ) -> dict:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, stage, progress, original_video_name,
                    video_size_bytes, video_sha256, video_path,
                    client_key, lyrics_source, lyrics_path, vocal_mode,
                    client_submission_id, input_mode,
                    source_upload_size_bytes, source_upload_sha256,
                    created_at, updated_at
                )
                VALUES (?, 'UPLOADED', 'UPLOAD_COMPLETE', 100,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    client_submission_id,
                    input_mode,
                    source_upload_size_bytes or video_size_bytes,
                    source_upload_sha256 or video_sha256,
                    timestamp,
                    timestamp,
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("Created job could not be read back")
        self.record_event_log(
            level="INFO",
            category="task",
            event="job.created",
            message="任务已创建并进入处理队列。",
            reference_type="job",
            reference_id=job_id,
            details={
                "input_mode": input_mode,
                "input_size_bytes": video_size_bytes,
                "lyrics_source": lyrics_source,
                "lyrics_provided": lyrics_path is not None,
                "vocal_mode": vocal_mode,
                "status": "UPLOADED",
                "stage": "UPLOAD_COMPLETE",
            },
        )
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
        client_submission_id: str | None = None,
    ) -> dict:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO upload_tickets (
                    id, status, client_key, video_name, video_size_bytes,
                    client_submission_id, created_at, updated_at, last_seen_at
                )
                VALUES (?, 'WAITING', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    client_key,
                    video_name,
                    video_size_bytes,
                    client_submission_id,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        ticket = self.get_upload_ticket(ticket_id)
        if ticket is None:
            raise RuntimeError("Created upload ticket could not be read back")
        self.record_event_log(
            level="INFO",
            category="upload",
            event="upload.queued",
            message="上传请求已进入队列。",
            reference_type="upload_ticket",
            reference_id=ticket_id,
            details={
                "status": "WAITING",
                "video_size_bytes": video_size_bytes,
            },
        )
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

    def touch_uploading_ticket(self, ticket_id: str) -> None:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE upload_tickets
                SET last_seen_at = ?, updated_at = ?
                WHERE id = ?
                  AND status = 'UPLOADING'
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
        for ticket_id in activated:
            self.record_event_log(
                level="INFO",
                category="upload",
                event="upload.ready",
                message="上传请求已获得上传名额。",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                details={"status": "READY"},
            )
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
        if upload_started:
            self.record_event_log(
                level="INFO",
                category="upload",
                event="upload.started",
                message="客户端已开始上传素材。",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                details={"status": "UPLOADING"},
            )
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
        completed = cursor.rowcount == 1
        if completed:
            self.record_event_log(
                level="INFO",
                category="upload",
                event="upload.completed",
                message="素材上传完成，任务已创建。",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                details={"job_id": job_id, "status": "COMPLETED"},
            )
        return completed

    def cancel_upload_ticket(self, ticket_id: str, *, actor: str = "user") -> bool:
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
        canceled = cursor.rowcount == 1
        if canceled:
            self.record_event_log(
                level="WARNING",
                category="upload",
                event="upload.canceled",
                message="上传请求已取消。",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                details={"status": "CANCELED", "actor": actor},
            )
        return canceled

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
        for ticket_id in ticket_ids:
            self.record_event_log(
                level="WARNING",
                category="upload",
                event="upload.expired",
                message="上传请求因长时间无活动而过期。",
                reference_type="upload_ticket",
                reference_id=ticket_id,
                details={"status": "EXPIRED"},
            )
        return ticket_ids

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_job_by_client_submission_id(
        self,
        client_submission_id: str,
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE client_submission_id = ?
                """,
                (client_submission_id,),
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
        logger.info(
            json.dumps(
                {
                    "event": "job_state_changed",
                    "job_id": job_id,
                    "status": status,
                    "stage": stage,
                    "progress": progress,
                    "error_code": error_code,
                },
                ensure_ascii=True,
            )
        )
        level = "ERROR" if status == "FAILED" else "INFO"
        if status == "CANCELED":
            level = "WARNING"
        message = (
            f"任务处理失败：{error_code or stage}"
            if status == "FAILED"
            else f"任务状态更新：{stage}"
        )
        self.record_event_log(
            level=level,
            category="task",
            event="job.state_changed",
            message=message,
            reference_type="job",
            reference_id=job_id,
            stage=stage,
            component="state_machine",
            details={
                "status": status,
                "stage": stage,
                "progress": progress,
                "error_code": error_code,
            },
        )
        if self.event_logger is not None and status == "PROCESSING":
            self.event_logger.progress(
                event="stage.progress",
                category="pipeline",
                message=f"处理阶段进度更新：{stage}",
                reference_id=job_id,
                stage=stage,
                component="state_machine",
                progress=progress,
                details={"status": status},
            )

    def queue_cloud_render(
        self,
        job_id: str,
        *,
        video_path: Path,
        video_size_bytes: int,
        video_sha256: str,
        timeline_path: Path,
        ass_path: Path,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'UPLOADED',
                    stage = 'CLOUD_RENDER_QUEUED',
                    progress = 10,
                    video_path = ?,
                    video_size_bytes = ?,
                    video_sha256 = ?,
                    timeline_path = ?,
                    ass_path = ?,
                    output_path = NULL,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND input_mode = 'AUDIO_ONLY'
                  AND status IN ('ALIGNED', 'SUBTITLE_GENERATED', 'COMPLETED')
                """,
                (
                    str(video_path),
                    video_size_bytes,
                    video_sha256,
                    str(timeline_path),
                    str(ass_path),
                    utc_now(),
                    job_id,
                ),
            )
        queued = cursor.rowcount == 1
        if queued:
            self.record_event_log(
                level="INFO",
                category="task",
                event="job.cloud_render_queued",
                message="任务已进入云端视频渲染队列。",
                reference_type="job",
                reference_id=job_id,
                details={
                    "status": "UPLOADED",
                    "stage": "CLOUD_RENDER_QUEUED",
                },
            )
        return queued

    def claim_reading_review(self, job_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET stage = 'READING_REVIEW_SAVING',
                    progress = 80,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'LYRICS_PROCESSED'
                  AND stage = 'READING_REVIEW_REQUIRED'
                """,
                (utc_now(), job_id),
            )
        return cursor.rowcount == 1

    def queue_alignment(self, job_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'UPLOADED',
                    stage = 'ALIGNMENT_QUEUED',
                    progress = 80,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'LYRICS_PROCESSED'
                  AND stage = 'READING_REVIEW_SAVING'
                """,
                (utc_now(), job_id),
            )
        queued = cursor.rowcount == 1
        if queued:
            self.record_event_log(
                level="INFO",
                category="task",
                event="job.alignment_queued",
                message="注音已确认，任务进入对齐队列。",
                reference_type="job",
                reference_id=job_id,
                details={
                    "status": "UPLOADED",
                    "stage": "ALIGNMENT_QUEUED",
                },
            )
        return queued

    def reopen_reading_review(self, job_id: str) -> dict | None:
        previous = self.get_job(job_id)
        if previous is None:
            return None
        timestamp = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'LYRICS_PROCESSED',
                    stage = 'READING_REVIEW_REQUIRED',
                    progress = 80,
                    timeline_path = NULL,
                    ass_path = NULL,
                    output_path = NULL,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('ALIGNED', 'SUBTITLE_GENERATED', 'COMPLETED')
                  AND lyrics_processed_path IS NOT NULL
                """,
                (timestamp, job_id),
            )
        if cursor.rowcount != 1:
            return None
        self.record_event_log(
            level="INFO",
            category="task",
            event="job.reading_review_reopened",
            message="任务已返回注音确认阶段。",
            reference_type="job",
            reference_id=job_id,
            stage="READING_REVIEW_REQUIRED",
            component="state_machine",
            details={
                "previous_status": previous["status"],
                "previous_stage": previous["stage"],
                "status": "LYRICS_PROCESSED",
                "stage": "READING_REVIEW_REQUIRED",
                "invalidated_artifacts": ["timeline", "subtitle", "video"],
            },
        )
        return self.get_job(job_id)

    def cancel_job(self, job_id: str, *, actor: str = "user") -> bool:
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
        canceled = cursor.rowcount == 1
        if canceled:
            self.record_event_log(
                level="WARNING",
                category="task",
                event="job.canceled",
                message="任务已取消。",
                reference_type="job",
                reference_id=job_id,
                details={
                    "status": "CANCELED",
                    "stage": "CANCELED_BY_USER",
                    "actor": actor,
                },
            )
        return canceled

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

    def count_jobs_by_status(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def count_upload_tickets_by_status(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM upload_tickets
                GROUP BY status
                """
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def list_active_upload_tickets(self, *, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, video_name, video_size_bytes, job_id,
                       created_at, updated_at, last_seen_at
                FROM upload_tickets
                WHERE status IN ('WAITING', 'READY', 'UPLOADING')
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_monitored_jobs(self, *, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, stage, progress, original_video_name,
                       video_size_bytes, error_code, error_message,
                       created_at, updated_at
                FROM jobs
                WHERE status IN ('UPLOADED', 'PROCESSING', 'FAILED')
                ORDER BY
                    CASE status
                        WHEN 'PROCESSING' THEN 0
                        WHEN 'UPLOADED' THEN 1
                        ELSE 2
                    END,
                    created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def requeue_job(self, job_id: str) -> dict | None:
        timestamp = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'UPLOADED',
                    stage = 'REQUEUED_BY_ADMIN',
                    progress = 0,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('FAILED', 'CANCELED')
                """,
                (timestamp, job_id),
            )
        if cursor.rowcount != 1:
            return None
        self.record_event_log(
            level="INFO",
            category="task",
            event="job.requeued",
            message="任务已由管理员重新加入处理队列。",
            reference_type="job",
            reference_id=job_id,
            details={"status": "UPLOADED", "stage": "REQUEUED_BY_ADMIN"},
        )
        return self.get_job(job_id)

    def retry_failed_job(self, job_id: str) -> dict | None:
        timestamp = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'UPLOADED',
                    stage = 'REQUEUED_BY_USER',
                    progress = 0,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'FAILED'
                """,
                (timestamp, job_id),
            )
        if cursor.rowcount != 1:
            return None
        self.record_event_log(
            level="INFO",
            category="task",
            event="job.retried",
            message="失败任务已由用户重新加入处理队列。",
            reference_type="job",
            reference_id=job_id,
            details={"status": "UPLOADED", "stage": "REQUEUED_BY_USER"},
        )
        return self.get_job(job_id)

    def record_admin_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        outcome: str,
        details: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO admin_audit_events (
                    action, target_type, target_id, outcome, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    target_type,
                    target_id,
                    outcome,
                    details,
                    utc_now(),
                ),
            )
        self.record_event_log(
            level="ERROR" if outcome == "failed" else "INFO",
            category="admin",
            event=action,
            message=f"管理员操作{('失败' if outcome == 'failed' else '完成')}：{action}",
            reference_type=target_type,
            reference_id=target_id,
            details={"outcome": outcome, "diagnostic": details},
        )

    def record_event_log(
        self,
        *,
        level: str,
        category: str,
        event: str,
        message: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        component: str | None = None,
        duration_ms: float | None = None,
        request_id: str | None = None,
        schema_version: int = 1,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self.event_logger is not None:
            self.event_logger.emit(
                level=level,
                category=category,
                event=event,
                message=message,
                reference_type=reference_type,
                reference_id=reference_id,
                run_id=run_id,
                stage=stage,
                component=component,
                duration_ms=duration_ms,
                request_id=request_id,
                details=details,
            )
            return
        try:
            self._insert_event_log(
                level=level,
                category=category,
                event=event,
                message=message,
                reference_type=reference_type,
                reference_id=reference_id,
                run_id=run_id,
                stage=stage,
                component=component,
                duration_ms=duration_ms,
                request_id=request_id,
                schema_version=schema_version,
                details=details,
            )
        except Exception as exc:
            logger.error(
                "Event log persistence failed for %s (%s)",
                event,
                type(exc).__name__,
            )

    def _insert_event_log(
        self,
        *,
        level: str,
        category: str,
        event: str,
        message: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        component: str | None = None,
        duration_ms: float | None = None,
        request_id: str | None = None,
        schema_version: int = 1,
        details: dict[str, Any] | None = None,
    ) -> None:
        serialized_details = (
            json.dumps(details, ensure_ascii=False, sort_keys=True)
            if details is not None
            else None
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_logs (
                    level, category, event, message, reference_type,
                    reference_id, run_id, stage, component, duration_ms,
                    request_id, schema_version, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    level.upper(),
                    category.lower(),
                    event,
                    message,
                    reference_type,
                    reference_id,
                    run_id,
                    stage,
                    component,
                    duration_ms,
                    request_id,
                    schema_version,
                    serialized_details,
                    utc_now(),
                ),
            )

    def list_event_logs(
        self,
        *,
        level: str | None = None,
        category: str | None = None,
        event: str | None = None,
        component: str | None = None,
        stage: str | None = None,
        reference_id: str | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        order: str = "desc",
    ) -> dict[str, Any]:
        conditions: list[str] = []
        parameters: list[object] = []
        if level:
            conditions.append("level = ?")
            parameters.append(level.upper())
        if category:
            conditions.append("category = ?")
            parameters.append(category.lower())
        if event:
            conditions.append("event = ?")
            parameters.append(event)
        if component:
            conditions.append("component = ?")
            parameters.append(component)
        if stage:
            conditions.append("stage = ?")
            parameters.append(stage)
        if reference_id:
            conditions.append("reference_id = ?")
            parameters.append(reference_id)
        if run_id:
            conditions.append("run_id = ?")
            parameters.append(run_id)
        if request_id:
            conditions.append("request_id = ?")
            parameters.append(request_id)
        if created_from:
            conditions.append("created_at >= ?")
            parameters.append(created_from)
        if created_to:
            conditions.append("created_at <= ?")
            parameters.append(created_to)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                "(event LIKE ? OR message LIKE ? OR reference_id LIKE ? "
                "OR details LIKE ?)"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sort_order = "ASC" if order.lower() == "asc" else "DESC"

        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM event_logs {where_clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT id, level, category, event, message, reference_type,
                       reference_id, run_id, stage, component, duration_ms,
                       request_id, schema_version, details, created_at
                FROM event_logs
                {where_clause}
                ORDER BY created_at {sort_order}, id {sort_order}
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            serialized_details = item.get("details")
            item["details"] = (
                json.loads(serialized_details) if serialized_details else {}
            )
            items.append(item)
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def cleanup_event_logs(self, *, older_than: str, max_rows: int) -> int:
        with self.connect() as connection:
            age_cursor = connection.execute(
                "DELETE FROM event_logs WHERE created_at < ?",
                (older_than,),
            )
            age_deleted = max(age_cursor.rowcount, 0)
            count = int(
                connection.execute("SELECT COUNT(*) FROM event_logs").fetchone()[0]
            )
            overflow = max(count - max_rows, 0)
            row_deleted = 0
            if overflow:
                cursor = connection.execute(
                    """
                    DELETE FROM event_logs
                    WHERE id IN (
                        SELECT id FROM event_logs
                        ORDER BY created_at ASC, id ASC
                        LIMIT ?
                    )
                    """,
                    (overflow,),
                )
                row_deleted = max(cursor.rowcount, 0)
        return age_deleted + row_deleted

    def list_job_event_timeline(
        self,
        job_id: str,
        *,
        run_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
        order: str = "asc",
    ) -> dict[str, Any]:
        conditions = [
            "(reference_id = ? OR reference_id IN "
            "(SELECT id FROM upload_tickets WHERE job_id = ?))"
        ]
        parameters: list[object] = [job_id, job_id]
        if run_id:
            conditions.append("run_id = ?")
            parameters.append(run_id)
        where_clause = f"WHERE {' AND '.join(conditions)}"
        sort_order = "ASC" if order.lower() == "asc" else "DESC"
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM event_logs {where_clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT id, level, category, event, message, reference_type,
                       reference_id, run_id, stage, component, duration_ms,
                       request_id, schema_version, details, created_at
                FROM event_logs
                {where_clause}
                ORDER BY created_at {sort_order}, id {sort_order}
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
            run_rows = connection.execute(
                """
                SELECT run_id, MIN(id) AS first_id
                FROM event_logs
                WHERE reference_id = ? AND run_id IS NOT NULL
                GROUP BY run_id
                ORDER BY first_id ASC
                """,
                (job_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            serialized_details = item.get("details")
            item["details"] = (
                json.loads(serialized_details) if serialized_details else {}
            )
            items.append(item)
        return {
            "job_id": job_id,
            "run_ids": [row["run_id"] for row in run_rows],
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def list_admin_audit_events(self, *, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, action, target_type, target_id, outcome,
                       details, created_at
                FROM admin_audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

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
            review_rows = connection.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'LYRICS_PROCESSED'
                  AND stage = 'READING_REVIEW_SAVING'
                """
            ).fetchall()
            connection.execute(
                """
                UPDATE jobs
                SET stage = 'READING_REVIEW_REQUIRED',
                    progress = 80,
                    updated_at = ?
                WHERE status = 'LYRICS_PROCESSED'
                  AND stage = 'READING_REVIEW_SAVING'
                """,
                (timestamp,),
            )
            rows = connection.execute(
                "SELECT id, stage FROM jobs WHERE status = 'PROCESSING'"
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
        for row in review_rows:
            self.record_event_log(
                level="WARNING",
                category="system",
                event="job.reading_review_recovered",
                message="服务重启后已恢复未完成的注音确认状态。",
                reference_type="job",
                reference_id=row["id"],
                stage="READING_REVIEW_REQUIRED",
                component="service_recovery",
                details={
                    "previous_stage": "READING_REVIEW_SAVING",
                    "restored_stage": "READING_REVIEW_REQUIRED",
                },
            )
        job_ids = [row["id"] for row in rows]
        for row in rows:
            self.record_event_log(
                level="ERROR",
                category="system",
                event="job.interrupted",
                message="服务重启中断了正在处理的任务。",
                reference_type="job",
                reference_id=row["id"],
                stage=row["stage"],
                component="service_recovery",
                details={
                    "status": "FAILED",
                    "error_code": "SERVICE_RESTARTED",
                    "interrupted_stage": row["stage"],
                },
            )
        return job_ids

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
