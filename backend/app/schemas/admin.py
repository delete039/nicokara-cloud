from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AdminOverviewResponse(BaseModel):
    generated_at: str
    upload_counts: dict[str, int]
    job_counts: dict[str, int]
    upload_tickets: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    runner: dict[str, Any]
    resources: dict[str, Any]
    audit_events: list[dict[str, Any]]


class AdminActionResponse(BaseModel):
    id: str
    status: str


class AdminQueueHealthResponse(BaseModel):
    status: str
    runner_healthy: bool
    upload_waiting: int
    jobs_waiting: int


class AdminLogItem(BaseModel):
    id: int
    level: str
    category: str
    event: str
    message: str
    reference_type: str | None
    reference_id: str | None
    run_id: str | None = None
    stage: str | None = None
    component: str | None = None
    duration_ms: float | None = None
    request_id: str | None = None
    schema_version: int = 1
    details: dict[str, Any]
    created_at: str


class AdminLogsResponse(BaseModel):
    items: list[AdminLogItem]
    total: int
    limit: int
    offset: int


class AdminJobTimelineResponse(AdminLogsResponse):
    job_id: str
    run_ids: list[str]
