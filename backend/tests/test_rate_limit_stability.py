from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.rate_limit import resolve_client_key
from app.main import create_app


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


def test_api_does_not_limit_completed_uploads_per_hour(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
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
        responses = []
        for index in range(7):
            response = client.post(
                "/api/v1/jobs",
                headers={"X-Forwarded-For": "198.51.100.20"},
                files=upload,
                data={"lyrics_text": f"歌词 {index}"},
            )
            responses.append(response)
            if response.status_code == 201:
                client.app.state.database.update_job_state(
                    response.json()["id"],
                    status="SUCCEEDED",
                    stage="COMPLETED",
                    progress=100,
                )

    assert [response.status_code for response in responses] == [201] * 7


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
