from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.services.uploads import (
    CHUNK_SIZE,
    SavedUpload,
    looks_like_audio,
    looks_like_mp4,
)


MAX_UPLOAD_CHUNK_BYTES = 16 * 1024 * 1024


def upload_sessions_root(storage_dir: Path) -> Path:
    return (storage_dir / "_uploads").resolve()


def upload_session_dir(storage_dir: Path, ticket_id: str) -> Path:
    root = upload_sessions_root(storage_dir)
    candidate = (root / ticket_id).resolve()
    if candidate.parent != root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload ticket.",
        )
    return candidate


def remove_chunked_upload(storage_dir: Path, ticket_id: str) -> None:
    session_dir = upload_session_dir(storage_dir, ticket_id)
    shutil.rmtree(session_dir, ignore_errors=True)


def touch_chunked_upload(storage_dir: Path, ticket_id: str) -> None:
    metadata_path = upload_session_dir(storage_dir, ticket_id) / "metadata.json"
    try:
        os.utime(metadata_path, None)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload chunk session does not exist.",
        ) from exc


def remove_stale_audio_uploads(
    storage_dir: Path,
    *,
    cutoff_timestamp: float,
) -> list[str]:
    root = upload_sessions_root(storage_dir)
    if not root.is_dir():
        return []

    removed: list[str] = []
    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue
        metadata_path = session_dir / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if metadata.get("upload_kind") != "audio":
            continue

        activity_paths = [metadata_path]
        chunks_dir = session_dir / "chunks"
        if chunks_dir.is_dir():
            activity_paths.extend(chunks_dir.glob("*.part"))
        try:
            last_activity = max(path.stat().st_mtime for path in activity_paths)
        except OSError:
            continue
        if last_activity >= cutoff_timestamp:
            continue
        shutil.rmtree(session_dir, ignore_errors=True)
        removed.append(session_dir.name)
    return removed


def acquire_completion_lock(storage_dir: Path, ticket_id: str) -> Path:
    lock_path = upload_session_dir(storage_dir, ticket_id) / "complete.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload chunks are already being finalized.",
        ) from exc
    else:
        os.close(descriptor)
    return lock_path


def start_chunked_upload(
    storage_dir: Path,
    ticket_id: str,
    *,
    video_name: str,
    video_size_bytes: int,
    chunk_size_bytes: int,
    total_chunks: int,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if video_size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video file is empty.",
        )
    if chunk_size_bytes <= 0 or chunk_size_bytes > MAX_UPLOAD_CHUNK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload chunk size.",
        )
    expected_chunks = max(
        1,
        (video_size_bytes + chunk_size_bytes - 1) // chunk_size_bytes,
    )
    if total_chunks != expected_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload chunk count.",
        )

    session_dir = upload_session_dir(storage_dir, ticket_id)
    shutil.rmtree(session_dir, ignore_errors=True)
    (session_dir / "chunks").mkdir(parents=True, exist_ok=False)
    metadata = {
        "ticket_id": ticket_id,
        "video_name": video_name,
        "video_size_bytes": video_size_bytes,
        "chunk_size_bytes": chunk_size_bytes,
        "total_chunks": total_chunks,
        **(extra_metadata or {}),
    }
    (session_dir / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return metadata


def read_chunked_upload_metadata(
    storage_dir: Path,
    ticket_id: str,
) -> dict[str, Any]:
    metadata_path = upload_session_dir(storage_dir, ticket_id) / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload chunk session does not exist.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload chunk session is corrupted.",
        ) from exc
    return metadata


def chunk_path(storage_dir: Path, ticket_id: str, chunk_index: int) -> Path:
    return (
        upload_session_dir(storage_dir, ticket_id)
        / "chunks"
        / f"{chunk_index:06d}.part"
    )


def received_chunk_count(storage_dir: Path, ticket_id: str) -> int:
    chunks_dir = upload_session_dir(storage_dir, ticket_id) / "chunks"
    if not chunks_dir.is_dir():
        return 0
    return sum(1 for path in chunks_dir.glob("*.part") if path.is_file())


def received_chunk_indices(storage_dir: Path, ticket_id: str) -> list[int]:
    metadata = read_chunked_upload_metadata(storage_dir, ticket_id)
    return [
        index
        for index in range(int(metadata["total_chunks"]))
        if chunk_path(storage_dir, ticket_id, index).is_file()
    ]


def missing_chunk_indices(storage_dir: Path, ticket_id: str) -> list[int]:
    metadata = read_chunked_upload_metadata(storage_dir, ticket_id)
    total_chunks = int(metadata["total_chunks"])
    return [
        index
        for index in range(total_chunks)
        if not chunk_path(storage_dir, ticket_id, index).is_file()
    ]


async def save_upload_chunk(
    storage_dir: Path,
    ticket_id: str,
    chunk_index: int,
    upload: UploadFile,
) -> dict[str, int]:
    metadata = read_chunked_upload_metadata(storage_dir, ticket_id)
    total_chunks = int(metadata["total_chunks"])
    chunk_size_bytes = int(metadata["chunk_size_bytes"])
    video_size_bytes = int(metadata["video_size_bytes"])

    if chunk_index < 0 or chunk_index >= total_chunks:
        await upload.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload chunk index is out of range.",
        )

    expected_size = (
        video_size_bytes - (chunk_size_bytes * chunk_index)
        if chunk_index == total_chunks - 1
        else chunk_size_bytes
    )
    touch_chunked_upload(storage_dir, ticket_id)
    destination = chunk_path(storage_dir, ticket_id, chunk_index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{uuid4().hex}.tmp"
    )
    total = 0

    try:
        with temporary.open("wb") as output:
            while data := await upload.read(CHUNK_SIZE):
                total += len(data)
                if total > chunk_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Upload chunk is too large.",
                    )
                output.write(data)
        if total != expected_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload chunk size does not match the session.",
            )
        temporary.replace(destination)
        touch_chunked_upload(storage_dir, ticket_id)
    finally:
        await upload.close()
        if temporary.exists():
            temporary.unlink(missing_ok=True)

    return {
        "received_chunks": received_chunk_count(storage_dir, ticket_id),
        "total_chunks": total_chunks,
    }


def assemble_chunked_mp4(
    storage_dir: Path,
    ticket_id: str,
    destination: Path,
    *,
    max_bytes: int,
) -> SavedUpload:
    metadata = read_chunked_upload_metadata(storage_dir, ticket_id)
    missing = missing_chunk_indices(storage_dir, ticket_id)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload chunks are incomplete.",
        )

    destination.parent.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    header = bytearray()
    total = 0

    try:
        with destination.open("wb") as output:
            for index in range(int(metadata["total_chunks"])):
                with chunk_path(storage_dir, ticket_id, index).open("rb") as chunk:
                    while data := chunk.read(CHUNK_SIZE):
                        total += len(data)
                        if total > max_bytes:
                            raise HTTPException(
                                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                                detail="Video file exceeds the size limit.",
                            )
                        if len(header) < 32:
                            header.extend(data[: 32 - len(header)])
                        digest.update(data)
                        output.write(data)

        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video file is empty.",
            )
        if total != int(metadata["video_size_bytes"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Merged video size does not match the session.",
            )
        if not looks_like_mp4(bytes(header)):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="File content is not a valid MP4 container.",
            )
        return SavedUpload(destination, total, digest.hexdigest())
    except Exception:
        shutil.rmtree(destination.parent, ignore_errors=True)
        raise


def assemble_chunked_audio(
    storage_dir: Path,
    ticket_id: str,
    destination: Path,
    *,
    max_bytes: int,
) -> SavedUpload:
    metadata = read_chunked_upload_metadata(storage_dir, ticket_id)
    missing = missing_chunk_indices(storage_dir, ticket_id)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio upload chunks are incomplete.",
        )

    destination.parent.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    header = bytearray()
    total = 0
    suffix = destination.suffix.lower()
    try:
        with destination.open("wb") as output:
            for index in range(int(metadata["total_chunks"])):
                with chunk_path(storage_dir, ticket_id, index).open("rb") as chunk:
                    while data := chunk.read(CHUNK_SIZE):
                        total += len(data)
                        if total > max_bytes:
                            raise HTTPException(
                                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                                detail="Audio file exceeds the size limit.",
                            )
                        if len(header) < 32:
                            header.extend(data[: 32 - len(header)])
                        digest.update(data)
                        output.write(data)
        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio file is empty.",
            )
        if total != int(metadata["video_size_bytes"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Merged audio size does not match the session.",
            )
        if not looks_like_audio(bytes(header), suffix):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="File content is not a supported audio format.",
            )
        return SavedUpload(destination, total, digest.hexdigest())
    except Exception:
        shutil.rmtree(destination.parent, ignore_errors=True)
        raise
