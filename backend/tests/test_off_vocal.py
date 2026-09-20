from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.tasks.pipeline import TranscriptionPipeline

JOB_ID = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"


def completed_job(db, root, *, video=True):
    folder = root / JOB_ID
    folder.mkdir(parents=True)
    source = folder / "input.mp4"
    source.write_bytes(b"source")
    timeline = folder / "reviewed_timeline.json"
    timeline.write_bytes(b"user adjusted timing and readings")
    output = folder / "final_karaoke.mp4"
    if video:
        output.write_bytes(b"rendered with reviewed subtitles")
    db.create_job(job_id=JOB_ID, original_video_name="song.mp4",
                  video_size_bytes=6, video_sha256="abc", video_path=source,
                  lyrics_source="text", lyrics_path=None,
                  input_mode="VIDEO" if video else "AUDIO_ONLY")
    db.update_job_state(JOB_ID, status="COMPLETED" if video else "SUBTITLE_GENERATED",
                        stage="VIDEO_RENDERING_COMPLETE" if video else "SUBTITLE_GENERATION_COMPLETE",
                        progress=100, timeline_path=timeline,
                        output_path=output if video else None)
    return folder


@pytest.mark.parametrize("video", [True, False])
@pytest.mark.parametrize("cached", [True, False])
def test_off_vocal_reuses_job_and_edits_without_recognition(tmp_path, video, cached):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    folder = completed_job(db, tmp_path / "jobs", video=video)
    stem = folder / "audio_instrumental.wav"
    if cached:
        stem.write_bytes(b"instrumental")

    class Extractor:
        def extract_stereo(self, source, destination):
            assert not cached
            destination.write_bytes(b"stereo")

    class Remover:
        def remove_vocals(self, source, destination):
            assert not cached
            destination.write_bytes(b"instrumental")

    class Renderer:
        def replace_audio(self, source, audio, destination):
            assert source.read_bytes() == b"rendered with reviewed subtitles"
            assert audio.read_bytes() == b"instrumental"
            destination.write_bytes(b"off video")

    db.queue_off_vocal(JOB_ID)
    TranscriptionPipeline(database=db, extractor=Extractor(), transcriber=None,
                          vocal_remover=Remover(), video_renderer=Renderer()).process(JOB_ID)
    job = db.get_job(JOB_ID)
    assert job["status"] == ("COMPLETED" if video else "SUBTITLE_GENERATED")
    assert job["vocal_mode"] == "off"
    assert Path(job["timeline_path"]).read_bytes() == b"user adjusted timing and readings"
    assert not (folder / "transcript.json").exists()
    if video:
        assert Path(job["output_path"]).read_bytes() == b"off video"
        assert (folder / "final_karaoke.mp4").read_bytes() == b"rendered with reviewed subtitles"


def test_off_vocal_failure_retry_keeps_conversion_stage(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    folder = completed_job(db, tmp_path / "jobs")
    (folder / "audio_instrumental.wav").write_bytes(b"instrumental")

    class BrokenRenderer:
        def replace_audio(self, *args):
            raise RuntimeError("mux failed")

    db.queue_off_vocal(JOB_ID)
    with pytest.raises(RuntimeError, match="mux failed"):
        TranscriptionPipeline(database=db, extractor=None, transcriber=None,
                              video_renderer=BrokenRenderer()).process(JOB_ID)
    assert db.get_job(JOB_ID)["status"] == "FAILED"
    assert db.get_job(JOB_ID)["vocal_mode"] == "on"
    assert (folder / "final_karaoke.mp4").read_bytes() == b"rendered with reviewed subtitles"
    assert db.retry_failed_job(JOB_ID)["stage"] == "OFF_VOCAL_QUEUED"


def test_off_vocal_api_is_idempotent_and_keeps_same_job(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs",
                              processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        completed_job(db, tmp_path / "jobs")
        for _ in range(2):
            response = client.post(f"/api/v1/jobs/{JOB_ID}/off-vocal")
            assert response.status_code == 200
            assert response.json()["id"] == JOB_ID
            assert response.json()["stage"] == "OFF_VOCAL_QUEUED"
            assert response.json()["off_vocal_conversion"] is True
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_off_vocal_rejects_unfinished_job(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    completed_job(db, tmp_path / "jobs")
    db.update_job_state(JOB_ID, status="PROCESSING", stage="ALIGNING", progress=90)
    assert db.queue_off_vocal(JOB_ID) is None


def test_replace_audio_copies_video_and_maps_only_instrumental(tmp_path, monkeypatch):
    import app.video.rendering as rendering

    source = tmp_path / "original.mp4"
    source.write_bytes(b"original video")
    audio = tmp_path / "instrumental.wav"
    audio.write_bytes(b"instrumental")
    output = tmp_path / "off.mp4"

    def run(command, **kwargs):
        assert command[command.index("-c:v") + 1] == "copy"
        assert "-vf" not in command
        maps = [command[i + 1] for i, arg in enumerate(command) if arg == "-map"]
        assert maps == ["0:v:0", "1:a:0"]
        output.write_bytes(b"off video")

    monkeypatch.setattr(rendering, "run_process", run)
    rendering.FFmpegVideoRenderer().replace_audio(source, audio, output)
    assert output.read_bytes() == b"off video"
    assert source.read_bytes() == b"original video"


def test_conversion_does_not_block_saving_reviewed_timeline(tmp_path):
    from test_jobs import reviewed_timeline_bytes
    from app.services.review_drafts import timeline_source_revision

    app = create_app(Settings(data_dir=tmp_path / "data", storage_dir=tmp_path / "jobs",
                              processing_enabled=False))
    with TestClient(app) as client:
        db = app.state.database
        folder = completed_job(db, tmp_path / "jobs", video=False)
        content = reviewed_timeline_bytes()
        (folder / "reviewed_timeline.json").write_bytes(content)
        revision = timeline_source_revision(db.get_job(JOB_ID), content)
        client.post(f"/api/v1/jobs/{JOB_ID}/off-vocal")
        import json
        review = json.loads(content)
        review["lines"][0]["tokens"][0]["moras"] = [
            {"reading": kana, "start_ms": 1000 + i * 100, "end_ms": 1100 + i * 100}
            for i, kana in enumerate("ものがたり")
        ]
        review["source_revision"] = revision
        review["base_saved_at"] = None
        response = client.put(f"/api/v1/jobs/{JOB_ID}/timeline-review", json=review)
        assert response.status_code == 200, response.text
        assert response.json()["timeline"]["source_revision"] == revision


def test_real_ffmpeg_replaces_audio_without_changing_video_packets(tmp_path):
    import shutil
    import subprocess
    from app.video.rendering import FFmpegVideoRenderer

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    original = tmp_path / "on.mp4"
    stem = tmp_path / "instrumental.wav"
    output = tmp_path / "off.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(original)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", str(stem)],
                   check=True, capture_output=True, timeout=20)
    FFmpegVideoRenderer(command=(ffmpeg,)).replace_audio(original, stem, output)

    def stream_hash(path, stream):
        return subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", stream,
                               "-c", "copy", "-f", "hash", "-hash", "sha256", "-"],
                              check=True, capture_output=True, timeout=20).stdout

    assert stream_hash(original, "0:v:0") == stream_hash(output, "0:v:0")
    assert stream_hash(original, "0:a:0") != stream_hash(output, "0:a:0")


def test_empty_separation_does_not_publish_off_vocal_or_corrupt_original(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    folder = completed_job(db, tmp_path / "jobs")

    class Extractor:
        def extract_stereo(self, source, destination):
            destination.write_bytes(b"stereo")

    class EmptyRemover:
        def remove_vocals(self, source, destination):
            destination.write_bytes(b"")

    db.queue_off_vocal(JOB_ID)
    with pytest.raises(RuntimeError, match="no instrumental"):
        TranscriptionPipeline(database=db, extractor=Extractor(), transcriber=None,
                              vocal_remover=EmptyRemover()).process(JOB_ID)
    job = db.get_job(JOB_ID)
    assert job["status"] == "FAILED"
    assert job["vocal_mode"] == "on"
    assert db.retry_failed_job(JOB_ID)["stage"] == "OFF_VOCAL_QUEUED"
    assert not (folder / "audio_instrumental.wav").exists()
    assert not (folder / "off_vocal_stereo.wav").exists()


def test_duplicate_conversion_reservations_only_queue_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db = Database(tmp_path / "db.sqlite3")
    db.initialize()
    completed_job(db, tmp_path / "jobs")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(db.queue_off_vocal, [JOB_ID, JOB_ID]))
    assert sum(result is not None for result in results) == 1
