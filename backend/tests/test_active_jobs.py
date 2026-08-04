from __future__ import annotations

from pathlib import Path

import pytest

from app.core.active_jobs import ActiveJobLimitError, ActiveJobLimiter
from app.core.database import Database


def test_active_job_slots_are_reserved_atomically(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    limiter = ActiveJobLimiter(database=database, max_active_jobs=1)

    reservation = limiter.reserve("198.51.100.40")
    with pytest.raises(ActiveJobLimitError):
        limiter.reserve("198.51.100.40")

    reservation.release()
    replacement = limiter.reserve("198.51.100.40")
    replacement.release()


def test_persisted_active_job_counts_toward_the_limit(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "jobs" / "job-1"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id="job-1",
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        client_key="198.51.100.41",
        lyrics_source="text",
        lyrics_path=None,
    )
    limiter = ActiveJobLimiter(database=database, max_active_jobs=1)

    with pytest.raises(ActiveJobLimitError):
        limiter.reserve("198.51.100.41")
