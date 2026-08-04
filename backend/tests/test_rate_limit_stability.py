from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.core.rate_limit import UploadRateLimiter, resolve_client_key
from app.main import create_app


def test_rate_limit_survives_limiter_recreation(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()

    first = UploadRateLimiter(
        database=database,
        max_requests=1,
        window_seconds=60,
    ).check("198.51.100.8", now=100)
    second = UploadRateLimiter(
        database=database,
        max_requests=1,
        window_seconds=60,
    ).check("198.51.100.8", now=101)

    assert first.allowed
    assert first.retry_after_seconds == 0
    assert not second.allowed
    assert second.retry_after_seconds == 59


def test_trusted_proxy_chain_uses_rightmost_untrusted_address() -> None:
    assert resolve_client_key(
        peer_host="127.0.0.1",
        forwarded_for="203.0.113.9, 10.0.0.5",
        trusted_proxies=("127.0.0.1", "10.0.0.0/8"),
    ) == "203.0.113.9"


def test_untrusted_peer_cannot_spoof_forwarded_address() -> None:
    assert resolve_client_key(
        peer_host="198.51.100.12",
        forwarded_for="203.0.113.9",
        trusted_proxies=("127.0.0.1",),
    ) == "198.51.100.12"


def test_api_rate_limit_survives_restart_and_separates_proxy_clients(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
        max_uploads_per_hour=1,
        trusted_proxy_hosts="testclient",
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
            headers={"X-Forwarded-For": "198.51.100.21"},
            files=upload,
            data={"lyrics_text": "歌詞"},
        )

    with TestClient(create_app(settings)) as client:
        repeated = client.post(
            "/api/v1/jobs",
            headers={"X-Forwarded-For": "198.51.100.21"},
            files=upload,
            data={"lyrics_text": "歌詞"},
        )
        other_user = client.post(
            "/api/v1/jobs",
            headers={"X-Forwarded-For": "198.51.100.22"},
            files=upload,
            data={"lyrics_text": "歌詞"},
        )

    assert first.status_code == 201
    assert repeated.status_code == 429
    assert 1 <= int(repeated.headers["retry-after"]) <= 3600
    assert other_user.status_code == 201


def test_api_prevents_one_client_from_occupying_the_whole_queue(
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
        max_uploads_per_hour=10,
        max_active_jobs_per_client=1,
        trusted_proxy_hosts="testclient",
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
            headers={"X-Forwarded-For": "198.51.100.31"},
            files=upload,
            data={"lyrics_text": "一"},
        )
        same_user = client.post(
            "/api/v1/jobs",
            headers={"X-Forwarded-For": "198.51.100.31"},
            files=upload,
            data={"lyrics_text": "二"},
        )
        other_user = client.post(
            "/api/v1/jobs",
            headers={"X-Forwarded-For": "198.51.100.32"},
            files=upload,
            data={"lyrics_text": "三"},
        )

    assert first.status_code == 201
    assert same_user.status_code == 429
    assert same_user.headers["retry-after"] == "60"
    assert other_user.status_code == 201
