from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.tasks.pipeline import TranscriptionPipeline


class RecordingRunner:
    def __init__(self):
        self.jobs = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def enqueue(self, job_id):
        self.jobs.append(job_id)


@pytest.fixture
def ready_job(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)) as client:
        database = client.app.state.database
        job_id = str(uuid4())
        directory = settings.storage_dir / job_id
        directory.mkdir()
        video = b"\x00\x00\x00\x18ftypisomvideo"
        (directory / "input.mp4").write_bytes(video)
        (directory / "audio.wav").write_bytes(b"audio")
        lyrics = {
            "provider": "local", "source_text": "song", "warnings": [],
            "lines": [{"source": "song", "surface": "song", "reading": "ki",
                       "tokens": [{"surface": "song", "reading": "ki"}]}],
        }
        (directory / "lyrics_processed.json").write_text(json.dumps(lyrics))
        timeline = {
            "confidence": 1, "warnings": [],
            "lines": [{"surface": "song", "reading": "ki", "start_ms": 1000,
                       "end_ms": 2000, "confidence": 1,
                       "tokens": [{"surface": "song", "reading": "ki",
                                   "start_ms": 1000, "end_ms": 2000,
                                   "confidence": 1, "moras": []}]}],
        }
        (directory / "timeline.json").write_text(json.dumps(timeline))
        (directory / "kirakara.ass").write_text("previous subtitle")
        database.create_job(
            job_id=job_id, original_video_name="song.mp4",
            video_size_bytes=len(video), video_sha256="source",
            video_path=directory / "input.mp4", lyrics_source="text",
            lyrics_path=None, input_mode="AUDIO_ONLY",
        )
        database.update_job_state(
            job_id, status="SUBTITLE_GENERATED", stage="SUBTITLE_GENERATION_COMPLETE",
            progress=100, audio_path=directory / "audio.wav",
            lyrics_processed_path=directory / "lyrics_processed.json",
            timeline_path=directory / "timeline.json", ass_path=directory / "kirakara.ass",
        )
        review = {
            "lines": [{"start_ms": 1200, "end_ms": 2400,
                       "tokens": [{"reading": "\u304d", "start_ms": 1200, "end_ms": 2400}]}],
            "base_saved_at": None,
            "source_revision": client.get(f"/api/v1/jobs/{job_id}/timeline").json().get("source_revision"),
        }
        yield client, database, job_id, directory, review, video, runner


@pytest.mark.parametrize("changed_status", ["PROCESSING", "SUBTITLE_GENERATED"])
def test_rejected_cloud_render_preserves_existing_files(ready_job, monkeypatch, changed_status):
    client, database, job_id, directory, review, video, runner = ready_job
    import app.api.mobile as mobile_api

    save_mp4 = mobile_api.save_mp4
    original_files = {path.name: path.read_bytes() for path in directory.iterdir()}

    async def concurrent_save(*args, **kwargs):
        saved = await save_mp4(*args, **kwargs)
        database.update_job_state(job_id, status=changed_status, stage="ANOTHER_REQUEST", progress=50)
        return saved

    monkeypatch.setattr(mobile_api, "save_mp4", concurrent_save)
    response = client.post(
        f"/api/v1/browser/jobs/{job_id}/cloud-render",
        files={"video": ("song.mp4", video, "video/mp4")},
        data={"timeline_review": json.dumps(review)},
    )
    assert response.status_code == 409
    assert runner.jobs == []
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == original_files


@pytest.mark.parametrize("retry_action", ["retry_failed_job", "requeue_job"])
@pytest.mark.parametrize("input_mode", ["AUDIO_ONLY", "VIDEO"])
def test_render_retry_preserves_reviewed_artifacts_after_restart(ready_job, retry_action, input_mode):
    client, database, job_id, directory, review, video, _runner = ready_job
    if input_mode == "AUDIO_ONLY":
        response = client.post(
            f"/api/v1/browser/jobs/{job_id}/cloud-render",
            files={"video": ("song.mp4", video, "video/mp4")},
            data={"timeline_review": json.dumps(review)},
        )
        assert response.status_code == 202
    else:
        with database.connect() as connection:
            connection.execute("UPDATE jobs SET input_mode = 'VIDEO', vocal_mode = 'off' WHERE id = ?", (job_id,))
        database.update_job_state(
            job_id, status="UPLOADED", stage="VIDEO_RENDER_QUEUED", progress=0,
            render_vocal_mode="on",
        )
    job = database.get_job(job_id)
    artifacts = {field: Path(job[field]).read_bytes() for field in ("video_path", "ass_path", "timeline_path")}

    class UnexpectedAnalysis:
        def __getattr__(self, name):
            pytest.fail(f"render retry must not run analysis: {name}")

    class Renderer:
        calls = 0

        def render(self, source, subtitle, destination, **kwargs):
            self.calls += 1
            assert source.read_bytes() == artifacts["video_path"]
            assert subtitle.read_bytes() == artifacts["ass_path"]
            assert kwargs["vocal_mode"] == "on"
            if self.calls == 1:
                raise RuntimeError("temporary rendering failure")
            destination.write_bytes(b"rendered")

    renderer = Renderer()
    pipeline = TranscriptionPipeline(
        database=database, extractor=UnexpectedAnalysis(), transcriber=UnexpectedAnalysis(),
        video_renderer=renderer,
    )
    with pytest.raises(RuntimeError, match="temporary rendering failure"):
        pipeline.process(job_id)
    restarted_database = Database(database.path)
    restarted_database.initialize()
    assert getattr(restarted_database, retry_action)(job_id) is not None
    pipeline.process(job_id)
    final = database.get_job(job_id)
    assert final["status"] == "COMPLETED"
    assert renderer.calls == 2
    assert {field: Path(final[field]).read_bytes() for field in artifacts} == artifacts


def test_reopened_readings_invalidate_even_an_identical_generated_timeline(ready_job):
    client, database, job_id, directory, review, *_ = ready_job
    saved = client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review)
    assert saved.status_code == 200
    assert client.post(f"/api/v1/jobs/{job_id}/readings/reopen").status_code == 200
    database.update_job_state(
        job_id, status="SUBTITLE_GENERATED", stage="SUBTITLE_GENERATION_COMPLETE", progress=100,
        timeline_path=directory / "timeline.json", ass_path=directory / "kirakara.ass",
    )
    restored = client.get(f"/api/v1/jobs/{job_id}/timeline-review")
    assert restored.status_code == 204
    assert client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review).status_code == 409


def test_stale_browser_cannot_overwrite_a_newer_cloud_draft(ready_job):
    client, _database, job_id, _directory, review, *_ = ready_job
    saved = client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review)
    assert saved.status_code == 200
    latest = {**review, "base_saved_at": saved.json()["saved_at"]}
    updated = client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=latest)
    assert updated.status_code == 200
    stale = client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review)
    assert stale.status_code == 409
    restored = client.get(f"/api/v1/jobs/{job_id}/timeline-review")
    assert restored.json()["saved_at"] == updated.json()["saved_at"]


def test_concurrent_draft_saves_have_only_one_winner(ready_job):
    client, _database, job_id, _directory, review, *_ = ready_job
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review),
            range(2),
        ))
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_unversioned_legacy_draft_is_retained_without_auto_restoring(ready_job):
    client, _database, job_id, directory, review, *_ = ready_job
    draft_path = directory / "timeline_review.json"
    content = json.dumps({"review": review, "saved_at": "2026-09-07T00:00:00Z"})
    draft_path.write_text(content)
    assert client.get(f"/api/v1/jobs/{job_id}/timeline-review").status_code == 204
    assert draft_path.read_text() == content


def test_malformed_cloud_draft_is_reported_without_overwriting_it(ready_job):
    client, _database, job_id, directory, review, *_ = ready_job
    draft_path = directory / "timeline_review.json"
    draft_path.write_text("{broken")
    assert client.get(f"/api/v1/jobs/{job_id}/timeline-review").status_code == 409
    response = client.put(f"/api/v1/jobs/{job_id}/timeline-review", json=review)
    assert response.status_code == 409
    assert draft_path.read_text() == "{broken"


def test_video_upload_resumes_only_missing_chunks(ready_job):
    client, _database, _job_id, _directory, _review, video, *_ = ready_job
    submission = str(uuid4())
    payload = {"video_name": "song.mp4", "video_size_bytes": len(video), "client_submission_id": submission}
    ticket = client.post("/api/v1/upload-tickets", json=payload).json()
    assert client.post("/api/v1/upload-tickets", json=payload).json()["id"] == ticket["id"]
    url = f"/api/v1/upload-tickets/{ticket['id']}/chunks"
    session = {"video_name": "song.mp4", "video_size_bytes": len(video), "chunk_size_bytes": 8, "total_chunks": 3}
    assert client.post(f"{url}/start", json=session).status_code == 200
    assert client.post(f"{url}/part/1", files={"chunk": ("part", video[8:16])}).status_code == 200
    resumed = client.post(f"{url}/start", json=session)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["received_chunk_indices"] == [1]
    assert resumed.json()["missing_chunk_indices"] == [0, 2]
    resized = client.post(f"{url}/start", json={**session, "chunk_size_bytes": 16})
    assert resized.status_code == 200
    assert resized.json()["chunk_size_bytes"] == session["chunk_size_bytes"]
    assert client.post(f"{url}/start", json={**session, "video_size_bytes": 18}).status_code == 409


def test_cloud_render_accepts_resumed_chunks_and_replays_completion(ready_job):
    client, database, job_id, _directory, review, video, runner = ready_job
    ticket = client.post("/api/v1/upload-tickets", json={
        "video_name": "song.mp4", "video_size_bytes": len(video), "client_submission_id": str(uuid4()),
    }).json()
    url = f"/api/v1/upload-tickets/{ticket['id']}/chunks"
    client.post(f"{url}/start", json={
        "video_name": "song.mp4", "video_size_bytes": len(video), "chunk_size_bytes": 8, "total_chunks": 3,
    })
    for index in range(3):
        assert client.post(f"{url}/part/{index}", files={"chunk": ("part", video[index * 8:(index + 1) * 8])}).status_code == 200
    endpoint = f"/api/v1/browser/jobs/{job_id}/cloud-render"
    payload = {"upload_ticket_id": ticket["id"], "timeline_review": json.dumps(review)}
    queued = client.post(endpoint, data=payload)
    assert queued.status_code == 202
    assert Path(database.get_job(job_id)["video_path"]).read_bytes() == video
    assert client.post(endpoint, data=payload).status_code == 202
    assert runner.jobs == [job_id]
    assert database.get_upload_ticket(ticket["id"])["status"] == "COMPLETED"
