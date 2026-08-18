from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.main import create_app
from app.services.chunked_uploads import start_chunked_upload
from app.tasks.cleanup import JobCleanupService


TEST_AUDIO_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024


def fake_wav(payload: bytes = b"audio") -> bytes:
    size = (36 + len(payload)).to_bytes(4, "little")
    data_size = len(payload).to_bytes(4, "little")
    return (
        b"RIFF"
        + size
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (16_000).to_bytes(4, "little")
        + (32_000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + data_size
        + payload
    )


def fake_mp4(payload: bytes = b"video") -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + payload


def upload_audio_chunk(
    client: TestClient,
    session_id: str,
    index: int,
    content: bytes,
):
    return client.post(
        f"/api/v1/browser/audio-uploads/{session_id}/chunks/part/{index}",
        files={
            "chunk": (
                f"chunk-{index}.part",
                content,
                "application/octet-stream",
            )
        },
    )


class RecordingRunner:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


def test_audio_upload_resumes_missing_chunks_and_creates_job(
    tmp_path: Path,
) -> None:
    audio = (
        b"\x00\x00\x00\x18ftypM4A "
        + b"a" * (TEST_AUDIO_UPLOAD_CHUNK_BYTES * 2 + 1024)
    )
    chunk_size = TEST_AUDIO_UPLOAD_CHUNK_BYTES
    submission_id = "11111111-2222-4333-8444-555555555555"
    request = {
        "audio_name": "song.audio.m4a",
        "audio_size_bytes": len(audio),
        "original_video_name": "song.mp4",
        "original_video_size_bytes": 120 * 1024 * 1024,
        "chunk_size_bytes": chunk_size,
        "total_chunks": (len(audio) + chunk_size - 1) // chunk_size,
        "client_submission_id": submission_id,
    }
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    runner = RecordingRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        started = client.post("/api/v1/browser/audio-uploads", json=request)
        session_id = started.json()["ticket_id"]
        first = upload_audio_chunk(client, session_id, 0, audio[:chunk_size])
        third = upload_audio_chunk(
            client,
            session_id,
            2,
            audio[2 * chunk_size : 3 * chunk_size],
        )

        resumed = client.post("/api/v1/browser/audio-uploads", json=request)
        for index in resumed.json()["missing_chunk_indices"]:
            upload_audio_chunk(
                client,
                session_id,
                index,
                audio[index * chunk_size : (index + 1) * chunk_size],
            )
        completed = client.post(
            f"/api/v1/browser/audio-uploads/{session_id}/complete",
            data={"lyrics_text": "君の知らない物語"},
        )

    assert started.status_code == 201
    assert first.status_code == 200
    assert third.status_code == 200
    assert resumed.status_code == 200
    assert resumed.json()["received_chunk_indices"] == [0, 2]
    assert completed.status_code == 201
    payload = completed.json()
    assert payload["input_mode"] == "AUDIO_ONLY"
    assert payload["original_video_name"] == "song.mp4"
    assert payload["video_size_bytes"] == 120 * 1024 * 1024
    assert (tmp_path / "jobs" / payload["id"] / "input_audio.m4a").read_bytes() == audio
    assert runner.job_ids == [payload["id"]]


def test_audio_upload_can_retry_completion_after_validation_failure(
    tmp_path: Path,
) -> None:
    audio = fake_wav()
    submission_id = "22222222-3333-4444-8555-666666666666"
    request = {
        "audio_name": "song.wav",
        "audio_size_bytes": len(audio),
        "original_video_name": "song.mp4",
        "original_video_size_bytes": 1024,
        "chunk_size_bytes": TEST_AUDIO_UPLOAD_CHUNK_BYTES,
        "total_chunks": 1,
        "client_submission_id": submission_id,
    }
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )

    with TestClient(create_app(settings, runner=RecordingRunner())) as client:
        session = client.post("/api/v1/browser/audio-uploads", json=request).json()
        uploaded = upload_audio_chunk(client, session["ticket_id"], 0, audio)
        invalid = client.post(
            f"/api/v1/browser/audio-uploads/{session['ticket_id']}/complete"
        )
        completed = client.post(
            f"/api/v1/browser/audio-uploads/{session['ticket_id']}/complete",
            data={"lyrics_text": "君の知らない物語"},
        )

    assert uploaded.status_code == 200
    assert invalid.status_code == 422
    assert completed.status_code == 201


def test_audio_upload_rejects_nonstandard_chunk_size(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/browser/audio-uploads",
            json={
                "audio_name": "song.wav",
                "audio_size_bytes": len(fake_wav()),
                "original_video_name": "song.mp4",
                "original_video_size_bytes": 1024,
                "chunk_size_bytes": 1024,
                "total_chunks": 1,
                "client_submission_id": (
                    "22333333-3444-4555-8666-777777777777"
                ),
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "音频分片大小必须为 8 MiB"


def test_audio_upload_accepts_overlapping_retries_for_the_same_chunk(
    tmp_path: Path,
) -> None:
    audio = fake_wav(b"overlapping-retry")
    submission_id = "23333333-3444-4555-8666-777777777777"
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    request = {
        "audio_name": "song.wav",
        "audio_size_bytes": len(audio),
        "original_video_name": "song.mp4",
        "original_video_size_bytes": 1024,
        "chunk_size_bytes": TEST_AUDIO_UPLOAD_CHUNK_BYTES,
        "total_chunks": 1,
        "client_submission_id": submission_id,
    }

    with TestClient(create_app(settings, runner=RecordingRunner())) as client:
        session = client.post("/api/v1/browser/audio-uploads", json=request).json()
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: upload_audio_chunk(
                        client,
                        session["ticket_id"],
                        0,
                        audio,
                    ),
                    range(2),
                )
            )
        completed = client.post(
            f"/api/v1/browser/audio-uploads/{session['ticket_id']}/complete",
            data={"lyrics_text": "君の知らない物語"},
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert completed.status_code == 201
    audio_path = tmp_path / "jobs" / completed.json()["id"] / "input_audio.wav"
    assert audio_path.read_bytes() == audio


def test_cleanup_removes_only_stale_audio_upload_sessions(tmp_path: Path) -> None:
    submission_id = "33333333-4444-4555-8666-777777777777"
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    request = {
        "audio_name": "song.wav",
        "audio_size_bytes": len(fake_wav()),
        "original_video_name": "song.mp4",
        "original_video_size_bytes": 1024,
        "chunk_size_bytes": TEST_AUDIO_UPLOAD_CHUNK_BYTES,
        "total_chunks": 1,
        "client_submission_id": submission_id,
    }

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/browser/audio-uploads", json=request)
        session_dir = tmp_path / "jobs" / "_uploads" / submission_id
        metadata_path = session_dir / "metadata.json"
        video_session_dir = tmp_path / "jobs" / "_uploads" / "video-session"
        start_chunked_upload(
            settings.storage_dir,
            "video-session",
            video_name="song.mp4",
            video_size_bytes=1024,
            chunk_size_bytes=1024,
            total_chunks=1,
        )
        old = datetime.now(UTC) - timedelta(minutes=5)
        os.utime(metadata_path, (old.timestamp(), old.timestamp()))
        os.utime(
            video_session_dir / "metadata.json",
            (old.timestamp(), old.timestamp()),
        )

        JobCleanupService(
            database=client.app.state.database,
            storage_dir=settings.storage_dir,
            retention_hours=24,
            upload_ticket_upload_timeout_seconds=60,
        ).run_once(now=datetime.now(UTC))

    assert created.status_code == 201
    assert not session_dir.exists()
    assert video_session_dir.exists()


def test_audio_only_contract_creates_an_audio_job_without_video_upload(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/browser/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "君の知らない物語",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": str(120 * 1024 * 1024),
                "client_submission_id": "11111111-1111-4111-8111-111111111111",
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["input_mode"] == "AUDIO_ONLY"
        assert payload["original_video_name"] == "song.mp4"
        assert payload["video_size_bytes"] == 120 * 1024 * 1024
        assert payload["source_upload_size_bytes"] == len(fake_wav())
        assert runner.job_ids == [payload["id"]]

        job = client.app.state.database.get_job(payload["id"])
        assert job is not None
        assert job["input_mode"] == "AUDIO_ONLY"
        assert Path(job["video_path"]).name == "input_audio.wav"
        assert Path(job["video_path"]).read_bytes() == fake_wav()


def test_audio_only_contract_rejects_non_audio_content(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/mobile/audio-jobs",
            files={"audio": ("song.wav", b"not audio", "audio/wav")},
            data={
                "lyrics_text": "歌詞",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": "1024",
            },
        )

    assert response.status_code == 415
    assert list((tmp_path / "jobs").iterdir()) == []


def test_legacy_mobile_audio_route_remains_available(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/mobile/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "歌詞",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": "1024",
            },
        )

    assert response.status_code == 201
    assert response.json()["input_mode"] == "AUDIO_ONLY"


def test_off_vocal_audio_job_exposes_generated_instrumental(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/browser/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "歌詞",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": "1024",
                "vocal_mode": "off",
            },
        )
        job_id = created.json()["id"]
        instrumental = settings.storage_dir / job_id / "audio_instrumental.wav"
        instrumental.write_bytes(fake_wav(b"instrumental"))

        response = client.get(f"/api/v1/jobs/{job_id}/instrumental")

    assert response.status_code == 200
    assert response.content == fake_wav(b"instrumental")
    assert response.headers["content-type"].startswith("audio/wav")


def test_on_vocal_audio_job_does_not_expose_instrumental(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/browser/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "歌詞",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": "1024",
                "vocal_mode": "on",
            },
        )

        response = client.get(
            f"/api/v1/jobs/{created.json()['id']}/instrumental"
        )

    assert response.status_code == 409


@pytest.mark.parametrize("ready_status", ["SUBTITLE_GENERATED", "COMPLETED"])
def test_audio_job_can_enter_cloud_render_queue_with_reviewed_timeline(
    tmp_path: Path,
    ready_status: str,
) -> None:
    video = fake_mp4()
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        created = client.post(
            "/api/v1/browser/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "今日",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": str(len(video)),
            },
        ).json()
        job_id = created["id"]
        job_dir = settings.storage_dir / job_id
        timeline_path = job_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(
                {
                    "confidence": 0.8,
                    "warnings": [],
                    "lines": [
                        {
                            "surface": "今日",
                            "reading": "きょう",
                            "start_ms": 1000,
                            "end_ms": 2000,
                            "confidence": 0.8,
                            "tokens": [
                                {
                                    "surface": "今日",
                                    "reading": "きょう",
                                    "start_ms": 1000,
                                    "end_ms": 2000,
                                    "confidence": 0.8,
                                    "moras": [],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status=ready_status,
            stage=(
                "VIDEO_RENDERING_COMPLETE"
                if ready_status == "COMPLETED"
                else "SUBTITLE_GENERATION_COMPLETE"
            ),
            progress=100,
            timeline_path=timeline_path,
            ass_path=job_dir / "lyrics.ass",
        )
        runner.job_ids.clear()

        response = client.post(
            f"/api/v1/browser/jobs/{job_id}/cloud-render",
            files={"video": ("song.mp4", video, "video/mp4")},
            data={
                "timeline_review": json.dumps(
                    {
                        "lines": [
                            {
                                "start_ms": 1200,
                                "end_ms": 2400,
                                "tokens": [
                                    {
                                        "reading": "こんにち",
                                        "start_ms": 1200,
                                        "end_ms": 2400,
                                    }
                                ],
                            }
                        ],
                        "style": {
                            "font_family": "Yu Gothic",
                            "font_size": 72,
                            "ruby_size": 30,
                            "stroke_width": 6,
                            "upper_y": 410,
                            "lower_y": 580,
                            "color_before": "#fefefe",
                            "color_after": "#123456",
                        },
                    },
                    ensure_ascii=False,
                )
            },
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "UPLOADED"
        assert payload["stage"] == "CLOUD_RENDER_QUEUED"
        assert payload["progress"] == 10
        assert payload["queue_position"] == 1
        assert runner.job_ids == [job_id]
        job = client.app.state.database.get_job(job_id)
        assert job is not None
        assert Path(job["video_path"]).read_bytes() == video
        assert json.loads(timeline_path.read_text(encoding="utf-8"))["lines"][0][
            "reading"
        ] == "こんにち"
        assert (job_dir / "kirakara.ass").exists()
        ass_content = (job_dir / "kirakara.ass").read_text(
            encoding="utf-8-sig"
        )
        assert "Style: KirakaraBase,Yu Gothic,108" in ass_content
        assert r"\an7\pos(192,615)" in ass_content
        assert "&H00563412" in ass_content


def test_cloud_render_rejects_a_video_that_does_not_match_the_audio_job(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/browser/audio-jobs",
            files={"audio": ("song.wav", fake_wav(), "audio/wav")},
            data={
                "lyrics_text": "今日",
                "original_video_name": "song.mp4",
                "original_video_size_bytes": str(len(fake_mp4())),
            },
        ).json()

        response = client.post(
            f"/api/v1/browser/jobs/{created['id']}/cloud-render",
            files={"video": ("other.mp4", fake_mp4(), "video/mp4")},
            data={"timeline_review": '{"lines": []}'},
        )

    assert response.status_code == 409
