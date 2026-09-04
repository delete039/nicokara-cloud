from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AdminTrafficPeriodResponse(BaseModel):
    key: str
    label: str
    started_at: str
    ended_at: str
    pageviews: int
    visits: int
    source: str


class AdminTrafficResponse(BaseModel):
    tracking_started_at: str
    pageviews: int
    visits: int
    pageviews_24h: int
    visits_24h: int
    active_visits: int
    pages_per_visit: float
    periods: list[AdminTrafficPeriodResponse]


class AdminOverviewResponse(BaseModel):
    generated_at: str
    traffic: AdminTrafficResponse
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
