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
