import json
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.tasks.pipeline import TranscriptionPipeline
from test_off_vocal import JOB_ID, completed_job
from test_jobs import fake_mp4, reviewed_timeline_bytes


def test_both_video_variants_remain_downloadable(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs", processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        folder = completed_job(db, tmp_path / "jobs")
        off = folder / "off.mp4"
        off.write_bytes(b"off video")
        db.update_job_state(JOB_ID, status="COMPLETED", stage="VIDEO_RENDERING_COMPLETE",
                            progress=100, output_path=off, render_vocal_mode="off")
        on = client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=on")
        assert on.content == b"rendered with reviewed subtitles"
        assert client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=off").content == b"off video"
        assert client.get(f"/api/v1/jobs/{JOB_ID}").json()["available_vocal_modes"] == ["on", "off"]


def test_preparing_instrumental_preserves_job_mode_and_completed_video(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs", processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        folder = completed_job(db, tmp_path / "jobs")
        response = client.post(f"/api/v1/jobs/{JOB_ID}/off-vocal?audio_only=true")
        assert response.status_code == 200
        assert response.json()["stage"] == "INSTRUMENTAL_QUEUED"

        class Extractor:
            def extract_stereo(self, source, target):
                target.write_bytes(b"stereo")

        class Remover:
            def remove_vocals(self, source, target):
                target.write_bytes(b"instrumental")

        TranscriptionPipeline(database=db, extractor=Extractor(), transcriber=None, vocal_remover=Remover()).process(JOB_ID)
        job = db.get_job(JOB_ID)
        assert job["vocal_mode"] == "on"
        assert job["status"] == "COMPLETED"
        assert Path(job["output_path"]) == folder / "final_karaoke.mp4"
        assert client.get(f"/api/v1/jobs/{JOB_ID}/instrumental").content == b"instrumental"
        assert client.get(f"/api/v1/jobs/{JOB_ID}").json()["instrumental_ready"] is True


@pytest.mark.parametrize("video_job", [True, False])
def test_cloud_render_uses_selected_mode_and_keeps_source_revision(tmp_path, video_job):
    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs", processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        folder = completed_job(db, tmp_path / "jobs", video=video_job)
        content = reviewed_timeline_bytes()
        timeline_path = folder / "reviewed_timeline.json"
        timeline_path.write_bytes(content)
        media = fake_mp4()
        with db.connect() as c:
            c.execute("UPDATE jobs SET video_size_bytes=? WHERE id=?", (len(media), JOB_ID))
        review = json.loads(content)
        review["lines"][0]["tokens"][0]["moras"] = []
        revision = client.get(f"/api/v1/jobs/{JOB_ID}/timeline").json()["source_revision"]
        review["source_revision"] = revision
        for mode in ["off", "on"]:
            response = client.post(f"/api/v1/browser/jobs/{JOB_ID}/cloud-render",
                                   files={"video": ("song.mp4", media, "video/mp4")},
                                   data={"timeline_review": json.dumps(review), "vocal_mode": mode})
            assert response.status_code == 202, response.text
            assert db.get_job(JOB_ID)["render_vocal_mode"] == mode

            class Extractor:
                def extract_stereo(self, source, target):
                    target.write_bytes(b"stereo")

            class Remover:
                def remove_vocals(self, source, target):
                    target.write_bytes(b"instrumental")

            class Renderer:
                def render(self, source, ass, target, *, vocal_mode, instrumental_audio_path):
                    assert vocal_mode == mode
                    assert (instrumental_audio_path is not None) == (mode == "off")
                    target.write_bytes(mode.encode())

            TranscriptionPipeline(database=db, extractor=Extractor(), transcriber=None,
                                  vocal_remover=Remover(), video_renderer=Renderer()).process(JOB_ID)
            assert Path(db.get_job(JOB_ID)["timeline_path"]) == timeline_path
            assert client.get(f"/api/v1/jobs/{JOB_ID}/timeline").json()["source_revision"] == revision
        assert client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=off").content == b"off"
        assert client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=on").content == b"on"


def test_failed_off_render_preserves_downloadable_on_video(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs", processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        folder = completed_job(db, tmp_path / "jobs")
        original = db.get_job(JOB_ID)
        ass = folder / "lyrics.ass"
        ass.write_text("[Script Info]")
        db.queue_cloud_render(JOB_ID, video_path=Path(original["video_path"]),
                              video_size_bytes=6, video_sha256="abc",
                              timeline_path=Path(original["timeline_path"]), ass_path=ass,
                              expected_updated_at=original["updated_at"], vocal_mode="off")
        with pytest.raises(RuntimeError, match="separation is unavailable"):
            TranscriptionPipeline(database=db, extractor=None, transcriber=None).process(JOB_ID)
        assert client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=on").content == b"rendered with reviewed subtitles"
        assert client.get(f"/api/v1/jobs/{JOB_ID}/download?vocal_mode=off").status_code == 409
        assert db.retry_failed_job(JOB_ID)["render_vocal_mode"] == "off"
        assert db.get_job(JOB_ID)["stage"] == "CLOUD_RENDER_QUEUED"


def test_existing_completed_result_is_backfilled_on_upgrade(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    folder = completed_job(db, tmp_path / "jobs")
    with db.connect() as c:
        c.execute("UPDATE jobs SET on_output_path=NULL WHERE id=?", (JOB_ID,))
    db.initialize()
    assert Path(db.get_job(JOB_ID)["on_output_path"]) == folder / "final_karaoke.mp4"


def test_reopening_readings_invalidates_both_export_versions(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    folder = completed_job(db, tmp_path / "jobs")
    with db.connect() as c:
        c.execute(
            "UPDATE jobs SET lyrics_processed_path=?, off_output_path=output_path, "
            "render_vocal_mode='off', render_timeline_path=timeline_path WHERE id=?",
            (str(folder / "lyrics_processed.json"), JOB_ID),
        )
    job = db.reopen_reading_review(JOB_ID)
    assert job["status"] == "LYRICS_PROCESSED"
    for field in ("on_output_path", "off_output_path", "render_timeline_path", "render_vocal_mode"):
        assert job[field] is None
    assert (folder / "final_karaoke.mp4").is_file()
