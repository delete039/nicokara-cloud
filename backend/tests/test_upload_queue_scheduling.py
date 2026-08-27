from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
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
    client_submission_id: str | None = None,
):
    return client.post(
        "/api/v1/upload-tickets",
        headers={"X-Forwarded-For": forwarded_for},
        json={
            "video_name": name,
            "video_size_bytes": size or len(fake_mp4()),
            "client_submission_id": client_submission_id,
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


def start_chunked_upload(
    client: TestClient,
    ticket_id: str,
    *,
    name: str,
    size: int,
    chunk_size: int,
):
    total_chunks = (size + chunk_size - 1) // chunk_size
    return client.post(
        f"/api/v1/upload-tickets/{ticket_id}/chunks/start",
        json={
            "video_name": name,
            "video_size_bytes": size,
            "chunk_size_bytes": chunk_size,
            "total_chunks": total_chunks,
        },
    )


def upload_chunk(
    client: TestClient,
    ticket_id: str,
    index: int,
    content: bytes,
):
    return client.post(
        f"/api/v1/upload-tickets/{ticket_id}/chunks/part/{index}",
        files={"chunk": (f"chunk-{index}.part", content, "application/octet-stream")},
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
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == uploaded.json()["id"]
    assert runner.job_ids == [uploaded.json()["id"]]


def test_completed_upload_can_be_recovered_by_client_submission_id(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = RecordingRunner()
    client_submission_id = "11111111-1111-4111-8111-111111111111"

    with TestClient(create_app(settings, runner=runner)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.52",
            client_submission_id=client_submission_id,
        ).json()

        uploaded = upload_for_ticket(
            client,
            ticket["id"],
            name=ticket["video_name"],
        )
        recovered = client.get(
            f"/api/v1/jobs/by-submission/{client_submission_id}"
        )

    assert uploaded.status_code == 201
    assert recovered.status_code == 200
    assert recovered.json()["id"] == uploaded.json()["id"]
    assert recovered.json()["client_submission_id"] == client_submission_id
    assert runner.job_ids == [uploaded.json()["id"]]


def test_chunked_upload_creates_job_after_all_parts(
    tmp_path: Path,
) -> None:
    content = fake_mp4(b"abcdefghijklmnopqrstuvwxyz")
    chunk_size = 10
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = RecordingRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.54",
            size=len(content),
        ).json()

        started = start_chunked_upload(
            client,
            ticket["id"],
            name=ticket["video_name"],
            size=len(content),
            chunk_size=chunk_size,
        )
        chunk_responses = [
            upload_chunk(
                client,
                ticket["id"],
                index,
                content[index * chunk_size : (index + 1) * chunk_size],
            )
            for index in range((len(content) + chunk_size - 1) // chunk_size)
        ]
        completed = client.post(
            f"/api/v1/upload-tickets/{ticket['id']}/chunks/complete",
            data={"lyrics_text": "lyrics"},
            files={
                "project_files": (
                    "lyrics_processed.reviewed.json",
                    json.dumps(
                        {
                            "provider": "local",
                            "source_text": "lyrics",
                            "lines": [
                                {
                                    "source": "lyrics",
                                    "surface": "lyrics",
                                    "reading": "りりっくす",
                                    "tokens": [
                                        {
                                            "surface": "lyrics",
                                            "reading": "りりっくす",
                                        }
                                    ],
                                }
                            ],
                            "warnings": [],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "application/json",
                )
            },
        )

    assert started.status_code == 200
    assert started.json()["status"] == "UPLOADING"
    assert [response.status_code for response in chunk_responses] == [200] * len(
        chunk_responses
    )
    assert completed.status_code == 201
    job_id = completed.json()["id"]
    assert (tmp_path / "jobs" / job_id / "input.mp4").read_bytes() == content
    assert (
        tmp_path / "jobs" / job_id / "imported_lyrics_processed.json"
    ).exists()
    assert not (tmp_path / "jobs" / "_uploads" / ticket["id"]).exists()
    assert runner.job_ids == [job_id]


def test_chunked_upload_complete_requires_all_parts(
    tmp_path: Path,
) -> None:
    content = fake_mp4(b"abcdefghijklmnopqrstuvwxyz")
    chunk_size = 10
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.55",
            size=len(content),
        ).json()

        started = start_chunked_upload(
            client,
            ticket["id"],
            name=ticket["video_name"],
            size=len(content),
            chunk_size=chunk_size,
        )
        uploaded = upload_chunk(client, ticket["id"], 0, content[:chunk_size])
        completed = client.post(
            f"/api/v1/upload-tickets/{ticket['id']}/chunks/complete",
            data={"lyrics_text": "lyrics"},
        )
        refreshed = client.get(f"/api/v1/upload-tickets/{ticket['id']}")

    assert started.status_code == 200
    assert uploaded.status_code == 200
    assert completed.status_code == 409
    assert refreshed.json()["status"] == "UPLOADING"


def test_chunked_upload_complete_is_locked_while_finalizing(
    tmp_path: Path,
) -> None:
    content = fake_mp4(b"abcdefghijklmnopqrstuvwxyz")
    chunk_size = 10
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.56",
            size=len(content),
        ).json()

        started = start_chunked_upload(
            client,
            ticket["id"],
            name=ticket["video_name"],
            size=len(content),
            chunk_size=chunk_size,
        )
        for index in range((len(content) + chunk_size - 1) // chunk_size):
            upload_chunk(
                client,
                ticket["id"],
                index,
                content[index * chunk_size : (index + 1) * chunk_size],
            )
        lock_path = tmp_path / "jobs" / "_uploads" / ticket["id"] / "complete.lock"
        lock_path.write_text("", encoding="utf-8")
        completed = client.post(
            f"/api/v1/upload-tickets/{ticket['id']}/chunks/complete",
            data={"lyrics_text": "lyrics"},
        )
        refreshed = client.get(f"/api/v1/upload-tickets/{ticket['id']}")

    assert started.status_code == 200
    assert completed.status_code == 409
    assert refreshed.json()["status"] == "UPLOADING"


def test_invalid_client_submission_id_is_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)

    with TestClient(create_app(settings)) as client:
        ticket = create_ticket(
            client,
            name="song.mp4",
            forwarded_for="198.51.100.53",
            client_submission_id="not-a-uuid",
        )
        recovered = client.get("/api/v1/jobs/by-submission/not-a-uuid")

    assert ticket.status_code == 400
    assert recovered.status_code == 400


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
