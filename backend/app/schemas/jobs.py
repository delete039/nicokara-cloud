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
    client_submission_id: str | None = None
    input_mode: str = "VIDEO"
    source_upload_size_bytes: int | None = None
    source_upload_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    queue_position: int | None = None
    queue_size: int | None = None
    created_at: datetime
    updated_at: datetime


class UploadTicketCreate(BaseModel):
    video_name: str
    video_size_bytes: int
    client_submission_id: str | None = None


class UploadTicketResponse(BaseModel):
    id: str
    status: str
    video_name: str
    video_size_bytes: int
    client_submission_id: str | None = None
    job_id: str | None = None
    queue_position: int | None = None
    queue_size: int | None = None
    created_at: datetime
    updated_at: datetime


class UploadChunkSessionCreate(BaseModel):
    video_name: str
    video_size_bytes: int
    chunk_size_bytes: int
    total_chunks: int


class UploadChunkSessionResponse(BaseModel):
    ticket_id: str
    status: str
    chunk_size_bytes: int
    total_chunks: int
    received_chunks: int


class UploadChunkResponse(BaseModel):
    ticket_id: str
    chunk_index: int
    received_chunks: int
    total_chunks: int


class HealthResponse(BaseModel):
    status: str

