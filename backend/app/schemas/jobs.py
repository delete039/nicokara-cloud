from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: str
    stage: str
    progress: int
    original_video_name: str
    video_size_bytes: int
    video_sha256: str
    lyrics_source: str | None = None
    vocal_mode: str = "on"
    error_code: str | None = None
    error_message: str | None = None
    queue_position: int | None = None
    queue_size: int | None = None
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str

