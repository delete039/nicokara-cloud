from __future__ import annotations

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
