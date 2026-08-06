from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


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


class RecordingRunner:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


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


def test_audio_job_can_enter_cloud_render_queue_with_reviewed_timeline(
    tmp_path: Path,
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
            status="SUBTITLE_GENERATED",
            stage="SUBTITLE_GENERATION_COMPLETE",
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
        assert r"\an4\pos(192,615)" in ass_content
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
