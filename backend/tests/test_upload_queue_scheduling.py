from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def fake_mp4(payload: bytes = b"video-data") -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + payload


class RecordingRunner:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


def build_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "storage_dir": tmp_path / "jobs",
        "processing_enabled": False,
        "cleanup_enabled": False,
        "trusted_proxy_hosts": "testclient",
    }
    values.update(overrides)
    return Settings(**values)


def create_ticket(
    client: TestClient,
    *,
    name: str,
    forwarded_for: str,
    size: int | None = None,
):
    return client.post(
        "/api/v1/upload-tickets",
        headers={"X-Forwarded-For": forwarded_for},
        json={
            "video_name": name,
            "video_size_bytes": size or len(fake_mp4()),
        },
    )


def upload_for_ticket(
    client: TestClient,
    ticket_id: str,
    *,
    name: str = "song.mp4",
    content: bytes | None = None,
):
    return client.post(
        f"/api/v1/upload-tickets/{ticket_id}/jobs",
        files={"video": (name, content or fake_mp4(), "video/mp4")},
        data={"lyrics_text": "lyrics"},
    )


def test_many_clients_are_scheduled_fifo_with_limited_upload_slots(
    tmp_path: Path,
) -> None:
    settings = build_settings(
        tmp_path,
        max_upload_slots=2,
        max_active_jobs_per_client=10,
    )
    runner = RecordingRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        created = [
            create_ticket(
                client,
                name=f"song-{index}.mp4",
                forwarded_for=f"198.51.100.{index + 1}",
            )
            for index in range(8)
        ]

        assert [response.status_code for response in created] == [201] * 8
        tickets = [response.json() for response in created]
        assert [ticket["status"] for ticket in tickets[:2]] == [
            "READY",
            "READY",
        ]
        assert [ticket["status"] for ticket in tickets[2:]] == ["WAITING"] * 6
        assert [ticket["queue_position"] for ticket in tickets[2:]] == [
            1,
            2,
            3,
            4,
            5,
            6,
        ]

        first_upload = upload_for_ticket(
            client,
            tickets[0]["id"],
            name=tickets[0]["video_name"],
        )
        second_upload = upload_for_ticket(
            client,
            tickets[1]["id"],
            name=tickets[1]["video_name"],
        )
        next_first = client.get(f"/api/v1/upload-tickets/{tickets[2]['id']}")
        next_second = client.get(f"/api/v1/upload-tickets/{tickets[3]['id']}")

    assert first_upload.status_code == 201
    assert second_upload.status_code == 201
    assert next_first.json()["status"] == "READY"
    assert next_second.json()["status"] == "READY"
    assert runner.job_ids == [
        first_upload.json()["id"],
        second_upload.json()["id"],
    ]


def test_waiting_ticket_cannot_upload_before_its_turn(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        first = create_ticket(
            client,
            name="first.mp4",
            forwarded_for="198.51.100.11",
        ).json()
        second = create_ticket(
            client,
            name="second.mp4",
            forwarded_for="198.51.100.12",
        ).json()

        early_upload = upload_for_ticket(
            client,
            second["id"],
            name=second["video_name"],
        )
        refreshed_first = client.get(f"/api/v1/upload-tickets/{first['id']}")
        refreshed_second = client.get(f"/api/v1/upload-tickets/{second['id']}")

    assert early_upload.status_code == 409
    assert refreshed_first.json()["status"] == "READY"
    assert refreshed_second.json()["status"] == "WAITING"


def test_one_client_cannot_fill_upload_queue_with_tickets(
    tmp_path: Path,
) -> None:
    settings = build_settings(
        tmp_path,
        max_upload_slots=1,
        max_active_jobs_per_client=2,
    )

    with TestClient(create_app(settings)) as client:
        first = create_ticket(
            client,
            name="first.mp4",
            forwarded_for="198.51.100.21",
        )
        second = create_ticket(
            client,
            name="second.mp4",
            forwarded_for="198.51.100.21",
        )
        third = create_ticket(
            client,
            name="third.mp4",
            forwarded_for="198.51.100.21",
        )
        other_client = create_ticket(
            client,
            name="other.mp4",
            forwarded_for="198.51.100.22",
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 429
    assert third.headers["retry-after"] == "60"
    assert other_client.status_code == 201


def test_canceling_ready_ticket_releases_next_waiting_client(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        first = create_ticket(
            client,
            name="first.mp4",
            forwarded_for="198.51.100.31",
        ).json()
        second = create_ticket(
            client,
            name="second.mp4",
            forwarded_for="198.51.100.32",
        ).json()

        canceled = client.post(f"/api/v1/upload-tickets/{first['id']}/cancel")
        refreshed_second = client.get(f"/api/v1/upload-tickets/{second['id']}")

    assert canceled.status_code == 200
    assert canceled.json()["status"] == "CANCELED"
    assert refreshed_second.json()["status"] == "READY"


def test_invalid_upload_cancels_ticket_and_releases_next_client(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        first = create_ticket(
            client,
            name="first.mp4",
            forwarded_for="198.51.100.41",
        ).json()
        second = create_ticket(
            client,
            name="second.mp4",
            forwarded_for="198.51.100.42",
        ).json()

        bad_upload = upload_for_ticket(
            client,
            first["id"],
            name=first["video_name"],
            content=b"not-an-mp4",
        )
        refreshed_first = client.get(f"/api/v1/upload-tickets/{first['id']}")
        refreshed_second = client.get(f"/api/v1/upload-tickets/{second['id']}")

    assert bad_upload.status_code == 415
    assert refreshed_first.json()["status"] == "CANCELED"
    assert refreshed_second.json()["status"] == "READY"
    assert list((tmp_path / "jobs").iterdir()) == []


def test_completed_ticket_cannot_be_uploaded_again(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = RecordingRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.51",
        ).json()

        uploaded = upload_for_ticket(
            client,
            ticket["id"],
            name=ticket["video_name"],
        )
        duplicate = upload_for_ticket(
            client,
            ticket["id"],
            name=ticket["video_name"],
        )

    assert uploaded.status_code == 201
    assert duplicate.status_code == 410
    assert runner.job_ids == [uploaded.json()["id"]]


def test_ready_upload_ticket_can_only_be_claimed_once_under_concurrency(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.56",
        ).json()
        barrier = threading.Barrier(8)

        def begin_upload() -> bool:
            barrier.wait(2)
            claimed = client.app.state.database.begin_upload_ticket(
                ticket["id"]
            )
            assert claimed is not None
            return bool(claimed["_upload_started"])

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: begin_upload(), range(8)))

        refreshed = client.get(f"/api/v1/upload-tickets/{ticket['id']}")

    assert sum(results) == 1
    assert refreshed.json()["status"] == "UPLOADING"


def test_stale_uploading_ticket_expires_and_releases_next_client(
    tmp_path: Path,
) -> None:
    settings = build_settings(
        tmp_path,
        max_upload_slots=1,
        upload_ticket_upload_timeout_seconds=1,
    )

    with TestClient(create_app(settings)) as client:
        first = create_ticket(
            client,
            name="first.mp4",
            forwarded_for="198.51.100.61",
        ).json()
        second = create_ticket(
            client,
            name="second.mp4",
            forwarded_for="198.51.100.62",
        ).json()
        ticket = client.app.state.database.begin_upload_ticket(first["id"])
        assert ticket["_upload_started"]
        old = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE upload_tickets SET updated_at = ? WHERE id = ?",
                (old, first["id"]),
            )

        refreshed_second = client.get(f"/api/v1/upload-tickets/{second['id']}")
        refreshed_first = client.get(f"/api/v1/upload-tickets/{first['id']}")

    assert refreshed_second.json()["status"] == "READY"
    assert refreshed_first.json()["status"] == "EXPIRED"


def test_upload_canceled_during_save_does_not_create_or_enqueue_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = RecordingRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        database = client.app.state.database
        original_complete = database.complete_upload_ticket

        def cancel_before_complete(ticket_id: str, job_id: str) -> bool:
            database.cancel_upload_ticket(ticket_id)
            return original_complete(ticket_id, job_id)

        monkeypatch.setattr(
            database,
            "complete_upload_ticket",
            cancel_before_complete,
        )
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.71",
        ).json()

        upload = upload_for_ticket(
            client,
            ticket["id"],
            name=ticket["video_name"],
        )
        refreshed = client.get(f"/api/v1/upload-tickets/{ticket['id']}")

    assert upload.status_code == 409
    assert refreshed.json()["status"] == "CANCELED"
    assert runner.job_ids == []
    assert list((tmp_path / "jobs").iterdir()) == []
