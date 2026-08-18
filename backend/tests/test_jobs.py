from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def fake_mp4(payload: bytes = b"video-data") -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + payload


def build_client(tmp_path: Path, *, max_video_bytes: int = 1024) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        max_video_bytes=max_video_bytes,
        processing_enabled=False,
    )
    return TestClient(create_app(settings))


def test_upload_mp4_and_lyrics(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君の知らない物語"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "UPLOADED"
        assert body["lyrics_source"] == "text"
        assert body["video_size_bytes"] == len(fake_mp4())

        status_response = client.get(f"/api/v1/jobs/{body['id']}")
        assert status_response.status_code == 200
        assert status_response.json()["video_sha256"] == body["video_sha256"]
        assert (tmp_path / "jobs" / body["id"] / "input.mp4").exists()
        assert (
            tmp_path / "jobs" / body["id"] / "lyrics.txt"
        ).read_text(encoding="utf-8") == "君の知らない物語\n"


def test_rejects_non_mp4_content(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", b"not-an-mp4", "video/mp4")},
        )

    assert response.status_code == 415
    assert list((tmp_path / "jobs").iterdir()) == []


def test_rejects_oversized_video(tmp_path: Path) -> None:
    with build_client(tmp_path, max_video_bytes=24) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(b"x" * 50), "video/mp4")},
        )

    assert response.status_code == 413


def test_rejects_two_lyrics_sources(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": ("song.mp4", fake_mp4(), "video/mp4"),
                "lyrics_file": ("lyrics.txt", "歌詞".encode(), "text/plain"),
            },
            data={"lyrics_text": "別の歌詞"},
        )

    assert response.status_code == 422
    assert list((tmp_path / "jobs").iterdir()) == []


def test_successful_upload_is_enqueued_for_processing(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self.job_ids: list[str] = []

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君の知らない物語"},
        )
        assert response.status_code == 201
        assert runner.started
        assert runner.job_ids == [response.json()["id"]]

    assert runner.stopped


def test_upload_ticket_delays_video_upload_until_a_slot_is_ready(
    tmp_path: Path,
) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        max_upload_slots=1,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        first_ticket = client.post(
            "/api/v1/upload-tickets",
            json={"video_name": "first.mp4", "video_size_bytes": 32},
        )
        second_ticket = client.post(
            "/api/v1/upload-tickets",
            json={"video_name": "second.mp4", "video_size_bytes": 32},
        )

        assert first_ticket.status_code == 201
        assert first_ticket.json()["status"] == "READY"
        assert second_ticket.status_code == 201
        assert second_ticket.json()["status"] == "WAITING"
        assert second_ticket.json()["queue_position"] == 1

        early_upload = client.post(
            f"/api/v1/upload-tickets/{second_ticket.json()['id']}/jobs",
            files={"video": ("second.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "まだ"},
        )
        assert early_upload.status_code == 409

        uploaded = client.post(
            f"/api/v1/upload-tickets/{first_ticket.json()['id']}/jobs",
            files={"video": ("first.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君の知らない物語"},
        )
        refreshed_second = client.get(
            f"/api/v1/upload-tickets/{second_ticket.json()['id']}"
        )

    assert uploaded.status_code == 201
    assert runner.job_ids == [uploaded.json()["id"]]
    assert refreshed_second.status_code == 200
    assert refreshed_second.json()["status"] == "READY"


def test_stale_upload_ticket_expires_and_releases_upload_slot(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        max_upload_slots=1,
        upload_ticket_timeout_seconds=1,
    )
    with TestClient(create_app(settings)) as client:
        first_ticket = client.post(
            "/api/v1/upload-tickets",
            json={"video_name": "first.mp4", "video_size_bytes": 32},
        )
        second_ticket = client.post(
            "/api/v1/upload-tickets",
            json={"video_name": "second.mp4", "video_size_bytes": 32},
        )
        old = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE upload_tickets SET last_seen_at = ? WHERE id = ?",
                (old, first_ticket.json()["id"]),
            )

        refreshed_second = client.get(
            f"/api/v1/upload-tickets/{second_ticket.json()['id']}"
        )
        refreshed_first = client.get(
            f"/api/v1/upload-tickets/{first_ticket.json()['id']}"
        )

    assert first_ticket.json()["status"] == "READY"
    assert second_ticket.json()["status"] == "WAITING"
    assert refreshed_second.json()["status"] == "READY"
    assert refreshed_first.json()["status"] == "EXPIRED"


def test_completed_transcript_can_be_downloaded(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君の知らない物語"},
        )
        job_id = response.json()["id"]
        transcript_path = tmp_path / "jobs" / job_id / "transcript.json"
        transcript = {
            "language": "ja",
            "text": "君の知らない物語",
            "segments": [],
        }
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="TRANSCRIBED",
            stage="TRANSCRIPTION_COMPLETE",
            progress=100,
            transcript_path=transcript_path,
        )

        transcript_response = client.get(f"/api/v1/jobs/{job_id}/transcript")

    assert transcript_response.status_code == 200
    assert transcript_response.json() == transcript


def test_processed_lyrics_can_be_downloaded(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "物語"},
        )
        job_id = response.json()["id"]
        lyrics_path = tmp_path / "jobs" / job_id / "lyrics_processed.json"
        processed = {
            "provider": "local",
            "source_text": "物語",
            "lines": [
                {
                    "source": "物語",
                    "surface": "物語",
                    "reading": "ものがたり",
                    "tokens": [{"surface": "物語", "reading": "ものがたり"}],
                }
            ],
            "warnings": ["local_reading_may_be_inaccurate"],
        }
        lyrics_path.write_text(
            json.dumps(processed, ensure_ascii=False),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="LYRICS_PROCESSED",
            stage="LYRIC_PROCESSING_COMPLETE",
            progress=100,
            lyrics_processed_path=lyrics_path,
        )

        lyrics_response = client.get(f"/api/v1/jobs/{job_id}/lyrics")

    assert lyrics_response.status_code == 200
    assert lyrics_response.json() == processed


def test_reviewed_readings_preserve_whitespace_before_alignment_is_queued(
    tmp_path: Path,
) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君 は"},
        )
        job_id = response.json()["id"]
        runner.job_ids.clear()
        lyrics_path = tmp_path / "jobs" / job_id / "lyrics_processed.json"
        lyrics_path.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "source_text": "君 は",
                    "lines": [
                        {
                            "source": "君 は",
                            "surface": "君 は",
                            "reading": "くん は",
                            "tokens": [
                                {"surface": "君", "reading": "くん"},
                                {"surface": " ", "reading": " "},
                                {
                                    "surface": "は",
                                    "reading": "は",
                                    "alignment_pronunciation": "wa",
                                },
                            ],
                        }
                    ],
                    "warnings": ["local_reading_may_be_inaccurate"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="LYRICS_PROCESSED",
            stage="READING_REVIEW_REQUIRED",
            progress=80,
            lyrics_processed_path=lyrics_path,
        )

        confirmed = client.post(
            f"/api/v1/jobs/{job_id}/readings",
            json={
                "lines": [
                    {
                        "surface": "君 は",
                        "tokens": [
                            {"surface": "君", "reading": "きみ"},
                            {"surface": " ", "reading": ""},
                            {"surface": "は", "reading": "わ"},
                        ],
                    }
                ]
            },
        )

        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "UPLOADED"
        assert confirmed.json()["stage"] == "ALIGNMENT_QUEUED"
        assert runner.job_ids == [job_id]
        saved = json.loads(lyrics_path.read_text(encoding="utf-8"))
        assert saved["lines"][0]["reading"] == "きみ わ"
        assert [token["reading"] for token in saved["lines"][0]["tokens"]] == [
            "きみ",
            " ",
            "わ",
        ]
        assert saved["lines"][0]["tokens"][2][
            "alignment_pronunciation"
        ] is None


def test_reading_review_rejects_changed_lyric_structure(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "物语"},
        )
        job_id = response.json()["id"]
        lyrics_path = tmp_path / "jobs" / job_id / "lyrics_processed.json"
        lyrics_path.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "source_text": "物语",
                    "lines": [
                        {
                            "source": "物语",
                            "surface": "物语",
                            "reading": "ものがたり",
                            "tokens": [
                                {"surface": "物语", "reading": "ものがたり"}
                            ],
                        }
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="LYRICS_PROCESSED",
            stage="READING_REVIEW_REQUIRED",
            progress=80,
            lyrics_processed_path=lyrics_path,
        )

        rejected = client.post(
            f"/api/v1/jobs/{job_id}/readings",
            json={
                "lines": [
                    {
                        "surface": "別の歌词",
                        "tokens": [
                            {"surface": "別の歌词", "reading": "べつのかし"}
                        ],
                    }
                ]
            },
        )

    assert rejected.status_code == 422


def test_reading_review_uses_generated_reading_when_review_is_empty(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君"},
        )
        job_id = response.json()["id"]
        lyrics_path = tmp_path / "jobs" / job_id / "lyrics_processed.json"
        lyrics_path.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "source_text": "君",
                    "lines": [
                        {
                            "source": "君",
                            "surface": "君",
                            "reading": "きみ",
                            "tokens": [{"surface": "君", "reading": "きみ"}],
                        }
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="LYRICS_PROCESSED",
            stage="READING_REVIEW_REQUIRED",
            progress=80,
            lyrics_processed_path=lyrics_path,
        )

        confirmed = client.post(
            f"/api/v1/jobs/{job_id}/readings",
            json={
                "lines": [
                    {
                        "surface": "君",
                        "tokens": [{"surface": "君", "reading": ""}],
                    }
                ]
            },
        )

        saved = json.loads(lyrics_path.read_text(encoding="utf-8"))

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "UPLOADED"
    assert confirmed.json()["stage"] == "ALIGNMENT_QUEUED"
    assert saved["lines"][0]["reading"] == "きみ"
    assert saved["lines"][0]["tokens"][0]["reading"] == "きみ"


def test_failed_job_can_be_retried_from_its_status_page(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君"},
        )
        job_id = response.json()["id"]
        runner.job_ids.clear()
        client.app.state.database.update_job_state(
            job_id,
            status="FAILED",
            stage="TRANSCRIBING",
            progress=40,
            error_code="TRANSCRIPTION_FAILED",
            error_message="failed",
        )

        retried = client.post(f"/api/v1/jobs/{job_id}/retry")

    assert retried.status_code == 200
    assert retried.json()["status"] == "UPLOADED"
    assert retried.json()["stage"] == "REQUEUED_BY_USER"
    assert retried.json()["progress"] == 0
    assert retried.json()["error_code"] is None
    assert runner.job_ids == [job_id]


def test_failed_job_retry_respects_the_clients_active_job_limit(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        max_active_jobs_per_client=1,
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        failed_response = client.post(
            "/api/v1/jobs",
            files={"video": ("failed.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君"},
        )
        failed_job_id = failed_response.json()["id"]
        client.app.state.database.update_job_state(
            failed_job_id,
            status="FAILED",
            stage="TRANSCRIBING",
            progress=40,
            error_code="TRANSCRIPTION_FAILED",
            error_message="failed",
        )
        active_response = client.post(
            "/api/v1/jobs",
            files={"video": ("active.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "君"},
        )

        retried = client.post(f"/api/v1/jobs/{failed_job_id}/retry")

    assert active_response.status_code == 201
    assert retried.status_code == 429
    assert retried.headers["Retry-After"] == "60"


def test_completed_timeline_can_be_downloaded(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "物語"},
        )
        job_id = response.json()["id"]
        timeline_path = tmp_path / "jobs" / job_id / "timeline.json"
        timeline = {
            "confidence": 0.92,
            "lines": [],
            "warnings": ["partial_alignment"],
        }
        timeline_path.write_text(
            json.dumps(timeline, ensure_ascii=False),
            encoding="utf-8",
        )
        client.app.state.database.update_job_state(
            job_id,
            status="ALIGNED",
            stage="ALIGNMENT_COMPLETE",
            progress=100,
            timeline_path=timeline_path,
        )

        timeline_response = client.get(f"/api/v1/jobs/{job_id}/timeline")

    assert timeline_response.status_code == 200
    assert timeline_response.json() == timeline


def test_generated_ass_can_be_downloaded(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "物語"},
        )
        job_id = response.json()["id"]
        ass_path = tmp_path / "jobs" / job_id / "lyrics.ass"
        content = "[Script Info]\nScriptType: v4.00+\n"
        ass_path.write_text(content, encoding="utf-8-sig")
        client.app.state.database.update_job_state(
            job_id,
            status="SUBTITLE_GENERATED",
            stage="SUBTITLE_GENERATION_COMPLETE",
            progress=100,
            ass_path=ass_path,
        )

        subtitle_response = client.get(f"/api/v1/jobs/{job_id}/subtitle")

    assert subtitle_response.status_code == 200
    assert subtitle_response.content.decode("utf-8-sig").splitlines() == (
        content.splitlines()
    )
    assert "lyrics.ass" in subtitle_response.headers["content-disposition"]


def _prepare_reviewable_job(client: TestClient, tmp_path: Path) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/jobs",
        files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
        data={"lyrics_text": "物語"},
    )
    job_id = response.json()["id"]
    job_dir = tmp_path / "jobs" / job_id
    timeline_path = job_dir / "timeline.json"
    timeline = {
        "confidence": 0.82,
        "alignment_engine": "mms_fa_kara",
        "alignment_model": "test-model",
        "warnings": [],
        "lines": [
            {
                "surface": "物語",
                "reading": "ものがたり",
                "start_ms": 1000,
                "end_ms": 3000,
                "confidence": 0.8,
                "tokens": [
                    {
                        "surface": "物語",
                        "reading": "ものがたり",
                        "start_ms": 1000,
                        "end_ms": 3000,
                        "confidence": 0.8,
                        "moras": [
                            {
                                "reading": reading,
                                "start_ms": 1000 + index * 400,
                                "end_ms": 1400 + index * 400,
                                "matched": True,
                                "confidence": 0.8,
                            }
                            for index, reading in enumerate("ものがたり")
                        ],
                    }
                ],
            }
        ],
    }
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False),
        encoding="utf-8",
    )
    lyrics_path = job_dir / "lyrics_processed.json"
    lyrics_path.write_text(
        json.dumps(
            {
                "provider": "local",
                "source_text": "物語",
                "lines": [
                    {
                        "source": "物語",
                        "surface": "物語",
                        "reading": "ものがたり",
                        "tokens": [
                            {
                                "surface": "物語",
                                "reading": "ものがたり",
                                "alignment_pronunciation": "monogatari",
                            }
                        ],
                    }
                ],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client.app.state.database.update_job_state(
        job_id,
        status="SUBTITLE_GENERATED",
        stage="SUBTITLE_GENERATION_COMPLETE",
        progress=100,
        timeline_path=timeline_path,
        lyrics_processed_path=lyrics_path,
    )
    review = {
        "lines": [
            {
                "start_ms": 2000,
                "end_ms": 4000,
                "tokens": [
                    {
                        "reading": "ものかたり",
                        "start_ms": 2000,
                        "end_ms": 4000,
                        "moras": [
                            {
                                "reading": reading,
                                "start_ms": 2000 + index * 400,
                                "end_ms": 2400 + index * 400,
                            }
                            for index, reading in enumerate("ものかたり")
                        ],
                    }
                ],
            }
        ],
        "style": {"font_size": 70, "color_after": "#112233"},
    }
    return job_id, review


def test_reviewed_timeline_export_uses_current_user_adjustments(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        job_id, review = _prepare_reviewable_job(client, tmp_path)
        original_path = tmp_path / "jobs" / job_id / "timeline.json"
        original_content = original_path.read_text(encoding="utf-8")

        response = client.post(
            f"/api/v1/jobs/{job_id}/exports/timeline",
            json=review,
        )

    assert response.status_code == 200
    exported = response.json()
    assert exported["lines"][0]["start_ms"] == 2000
    assert exported["lines"][0]["tokens"][0]["reading"] == "ものかたり"
    assert exported["lines"][0]["tokens"][0]["moras"][0] == {
        "reading": "も",
        "start_ms": 2000,
        "end_ms": 2400,
        "matched": True,
        "confidence": 1.0,
    }
    assert "browser_reviewed" in exported["warnings"]
    assert original_path.read_text(encoding="utf-8") == original_content


def test_reviewed_lyrics_export_uses_current_user_readings(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        job_id, review = _prepare_reviewable_job(client, tmp_path)

        response = client.post(
            f"/api/v1/jobs/{job_id}/exports/lyrics",
            json=review,
        )

    assert response.status_code == 200
    exported = response.json()
    assert exported["lines"][0]["reading"] == "ものかたり"
    assert exported["lines"][0]["tokens"][0]["reading"] == "ものかたり"
    assert exported["lines"][0]["tokens"][0]["alignment_pronunciation"] is None


def test_reviewed_ass_export_uses_current_timing_and_style(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        job_id, review = _prepare_reviewable_job(client, tmp_path)

        response = client.post(
            f"/api/v1/jobs/{job_id}/exports/subtitle",
            json=review,
        )

    assert response.status_code == 200
    content = response.content.decode("utf-8-sig")
    assert "Dialogue: 3,0:00:02.00" in content
    assert "Style: KirakaraBase,Noto Sans CJK JP,105" in content
    assert "&H00332211" in content
    assert "lyrics.reviewed.ass" in response.headers["content-disposition"]


def test_final_video_can_be_streamed_and_downloaded(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "物語"},
        )
        job_id = response.json()["id"]
        output_path = tmp_path / "jobs" / job_id / "final_karaoke.mp4"
        content = fake_mp4(b"rendered")
        output_path.write_bytes(content)
        client.app.state.database.update_job_state(
            job_id,
            status="COMPLETED",
            stage="VIDEO_RENDERING_COMPLETE",
            progress=100,
            output_path=output_path,
        )

        result_response = client.get(f"/api/v1/jobs/{job_id}/result")
        range_response = client.get(
            f"/api/v1/jobs/{job_id}/result",
            headers={"Range": "bytes=0-9"},
        )
        download_response = client.get(
            f"/api/v1/jobs/{job_id}/download"
        )

    assert result_response.status_code == 200
    assert result_response.content == content
    assert result_response.headers["content-type"].startswith("video/mp4")
    assert "attachment" not in result_response.headers.get(
        "content-disposition",
        "",
    )
    assert range_response.status_code == 206
    assert range_response.content == content[:10]
    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["content-disposition"]
    assert "final_karaoke.mp4" in download_response.headers[
        "content-disposition"
    ]
