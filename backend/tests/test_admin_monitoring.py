from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class MonitoringRunner:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.canceled: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)

    async def cancel(self, job_id: str) -> bool:
        self.canceled.append(job_id)
        return True

    def snapshot(self) -> dict:
        return {
            "healthy": True,
            "worker_count": 1,
            "alive_workers": 1,
            "queued_in_memory": 0,
            "last_heartbeat_at": "2026-08-05T00:00:00+00:00",
            "active_jobs": [],
        }


def build_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "storage_dir": tmp_path / "jobs",
        "processing_enabled": False,
        "cleanup_enabled": False,
        "admin_token": "monitor-secret",
    }
    values.update(overrides)
    return Settings(**values)


def auth_headers(token: str = "monitor-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_job(database, storage_dir: Path, job_id: str) -> None:
    job_dir = storage_dir / job_id
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )


def test_admin_monitor_requires_configured_bearer_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with TestClient(create_app(settings, runner=MonitoringRunner())) as client:
        missing = client.get("/api/v1/admin/overview")
        wrong = client.get(
            "/api/v1/admin/overview",
            headers=auth_headers("wrong-token"),
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert "WWW-Authenticate" in missing.headers

    disabled = build_settings(tmp_path / "disabled", admin_token="")
    with TestClient(create_app(disabled, runner=MonitoringRunner())) as client:
        unavailable = client.get(
            "/api/v1/admin/overview",
            headers=auth_headers(),
        )

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == (
        "管理员监控尚未配置，请在服务端设置 "
        "NICOKARA_ADMIN_TOKEN 后重启服务。"
    )


def test_admin_overview_reports_upload_processing_worker_and_resources(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = MonitoringRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        database = client.app.state.database
        first = database.create_upload_ticket(
            ticket_id="10000000-0000-0000-0000-000000000001",
            client_key="private-client-one",
            video_name="first.mp4",
            video_size_bytes=1024,
        )
        second = database.create_upload_ticket(
            ticket_id="10000000-0000-0000-0000-000000000002",
            client_key="private-client-two",
            video_name="second.mp4",
            video_size_bytes=2048,
        )
        database.activate_upload_tickets(max_active_uploads=1)

        job_id = "20000000-0000-0000-0000-000000000001"
        create_job(database, settings.storage_dir, job_id)
        database.update_job_state(
            job_id,
            status="PROCESSING",
            stage="TRANSCRIBING",
            progress=40,
        )

        response = client.get(
            "/api/v1/admin/overview",
            headers=auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["upload_counts"]["READY"] == 1
    assert body["upload_counts"]["WAITING"] == 1
    assert body["job_counts"]["PROCESSING"] == 1
    assert [ticket["id"] for ticket in body["upload_tickets"]] == [
        first["id"],
        second["id"],
    ]
    assert body["upload_tickets"][0]["queue_position"] is None
    assert body["upload_tickets"][1]["queue_position"] == 1
    assert body["jobs"][0]["stage"] == "TRANSCRIBING"
    assert body["jobs"][0]["stage_age_seconds"] >= 0
    assert body["runner"]["healthy"] is True
    assert body["resources"]["disk"]["total_bytes"] > 0
    assert "private-client" not in response.text


def test_admin_can_cancel_upload_and_requeue_failed_job_with_audit(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, max_upload_slots=1)
    runner = MonitoringRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        database = client.app.state.database
        ticket = database.create_upload_ticket(
            ticket_id="30000000-0000-0000-0000-000000000001",
            client_key="private-client",
            video_name="cancel-me.mp4",
            video_size_bytes=1024,
        )
        database.activate_upload_tickets(max_active_uploads=1)

        job_id = "40000000-0000-0000-0000-000000000001"
        create_job(database, settings.storage_dir, job_id)
        database.update_job_state(
            job_id,
            status="FAILED",
            stage="TRANSCRIBING",
            progress=40,
            error_code="TRANSCRIPTION_FAILED",
            error_message="failed",
        )

        canceled = client.post(
            f"/api/v1/admin/upload-tickets/{ticket['id']}/cancel",
            headers=auth_headers(),
        )
        requeued = client.post(
            f"/api/v1/admin/jobs/{job_id}/requeue",
            headers=auth_headers(),
        )
        overview = client.get(
            "/api/v1/admin/overview",
            headers=auth_headers(),
        ).json()

    assert canceled.status_code == 200
    assert canceled.json()["status"] == "CANCELED"
    assert requeued.status_code == 200
    assert requeued.json()["status"] == "UPLOADED"
    assert runner.enqueued == [job_id]
    assert [event["action"] for event in overview["audit_events"][:2]] == [
        "job.requeue",
        "upload_ticket.cancel",
    ]
    upload_event = database.list_event_logs(
        event="upload.canceled", reference_id=ticket["id"]
    )["items"][0]
    assert upload_event["details"]["actor"] == "administrator"


def test_admin_cancel_job_is_distinguishable_from_user_cancel(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    runner = MonitoringRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        database = client.app.state.database
        job_id = "41000000-0000-0000-0000-000000000001"
        create_job(database, settings.storage_dir, job_id)
        response = client.post(
            f"/api/v1/admin/jobs/{job_id}/cancel",
            headers=auth_headers(),
        )
        event = database.list_event_logs(
            event="job.canceled", reference_id=job_id
        )["items"][0]

    assert response.status_code == 200
    assert event["details"]["actor"] == "administrator"
    assert event["details"]["stage"] == "CANCELED_BY_USER"


def test_admin_queue_health_is_probeable_and_fails_when_workers_are_unhealthy(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    runner = MonitoringRunner()

    with TestClient(create_app(settings, runner=runner)) as client:
        healthy = client.get(
            "/api/v1/admin/queue-health",
            headers=auth_headers(),
        )
        runner.snapshot = lambda: {
            "healthy": False,
            "worker_count": 1,
            "alive_workers": 0,
            "queued_in_memory": 2,
            "last_heartbeat_at": "2026-08-05T00:00:00+00:00",
            "active_jobs": [],
        }
        unhealthy = client.get(
            "/api/v1/admin/queue-health",
            headers=auth_headers(),
        )

    assert healthy.status_code == 200
    assert healthy.json() == {
        "status": "ok",
        "runner_healthy": True,
        "upload_waiting": 0,
        "jobs_waiting": 0,
    }
    assert unhealthy.status_code == 503
    assert unhealthy.json()["status"] == "degraded"


def test_admin_logs_are_protected_filterable_and_paginated(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with TestClient(create_app(settings, runner=MonitoringRunner())) as client:
        database = client.app.state.database
        job_id = "50000000-0000-0000-0000-000000000001"
        create_job(database, settings.storage_dir, job_id)
        database.update_job_state(
            job_id,
            status="FAILED",
            stage="TRANSCRIBING",
            progress=40,
            error_code="TRANSCRIPTION_FAILED",
            error_message="Audio transcription failed.",
        )
        database.record_admin_audit(
            action="job.inspect",
            target_type="job",
            target_id=job_id,
            outcome="succeeded",
        )

        unauthorized = client.get("/api/v1/admin/logs")
        filtered = client.get(
            "/api/v1/admin/logs",
            headers=auth_headers(),
            params={
                "level": "ERROR",
                "category": "task",
                "reference_id": job_id,
                "query": "TRANSCRIPTION_FAILED",
                "limit": 1,
                "offset": 0,
            },
        )
        second_page = client.get(
            "/api/v1/admin/logs",
            headers=auth_headers(),
            params={"limit": 1, "offset": 1},
        )

    assert unauthorized.status_code == 401
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["items"][0] == {
        "id": body["items"][0]["id"],
        "level": "ERROR",
        "category": "task",
        "event": "job.state_changed",
        "message": "任务处理失败：TRANSCRIPTION_FAILED",
        "reference_type": "job",
        "reference_id": job_id,
        "run_id": None,
        "stage": "TRANSCRIBING",
        "component": "state_machine",
        "duration_ms": None,
        "request_id": None,
        "schema_version": 1,
        "details": {
            "error_code": "TRANSCRIPTION_FAILED",
            "progress": 40,
            "stage": "TRANSCRIBING",
            "status": "FAILED",
        },
        "created_at": body["items"][0]["created_at"],
    }
    assert second_page.status_code == 200
    assert second_page.json()["total"] >= 3
    assert len(second_page.json()["items"]) == 1
    assert "Audio transcription failed" not in filtered.text


def test_admin_logs_support_structured_filters_and_stable_job_timeline(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)

    with TestClient(create_app(settings, runner=MonitoringRunner())) as client:
        database = client.app.state.database
        ticket = database.create_upload_ticket(
            ticket_id="60000000-0000-0000-0000-000000000001",
            client_key="private-client",
            video_name="song.mp4",
            video_size_bytes=123,
        )
        database.activate_upload_tickets(max_active_uploads=1)
        database.begin_upload_ticket(ticket["id"])
        job_id = "70000000-0000-0000-0000-000000000001"
        create_job(database, settings.storage_dir, job_id)
        assert database.complete_upload_ticket(ticket["id"], job_id)
        database.record_event_log(
            level="INFO",
            category="pipeline",
            event="stage.started",
            message="开始歌词对齐",
            reference_type="job",
            reference_id=job_id,
            run_id="run-a",
            stage="ALIGNING",
            component="fa_kara",
            request_id="request-a",
            details={"model": "mms"},
        )
        database.record_event_log(
            level="WARNING",
            category="pipeline",
            event="stage.fallback",
            message="切换普通对齐器",
            reference_type="job",
            reference_id=job_id,
            run_id="run-b",
            stage="ALIGNING",
            component="fa_kara",
            request_id="request-b",
            details={"reason": "low confidence"},
        )

        filtered = client.get(
            "/api/v1/admin/logs",
            headers=auth_headers(),
            params={
                "event": "stage.fallback",
                "component": "fa_kara",
                "stage": "ALIGNING",
                "run_id": "run-b",
                "request_id": "request-b",
                "order": "asc",
            },
        )
        timeline = client.get(
            f"/api/v1/admin/jobs/{job_id}/timeline",
            headers=auth_headers(),
            params={"order": "asc", "limit": 200},
        )
        run_timeline = client.get(
            f"/api/v1/admin/jobs/{job_id}/timeline",
            headers=auth_headers(),
            params={"run_id": "run-a", "order": "asc"},
        )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["run_id"] == "run-b"
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["job_id"] == job_id
    assert body["run_ids"] == ["run-a", "run-b"]
    assert any(
        item["reference_id"] == ticket["id"]
        and item["event"] == "upload.queued"
        for item in body["items"]
    )
    ordering = [(item["created_at"], item["id"]) for item in body["items"]]
    assert ordering == sorted(ordering)
    assert run_timeline.status_code == 200
    assert {item["run_id"] for item in run_timeline.json()["items"]} == {
        "run-a"
    }
