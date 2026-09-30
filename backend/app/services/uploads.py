from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from app.core.resource_limits import check_disk_space
from app.video.formats import looks_like_video


CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    size_bytes: int
    sha256: str


def looks_like_mp4(header: bytes) -> bool:
    """Compatibility wrapper for integrations that still import this helper."""
    return looks_like_video(header, ".mp4")


def looks_like_audio(header: bytes, suffix: str) -> bool:
    if suffix == ".wav":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    if suffix in {".m4a", ".mp4"}:
        return looks_like_video(header, ".mp4")
    if suffix == ".aac":
        return len(header) >= 2 and header[0] == 0xFF and header[1] & 0xF0 == 0xF0
    if suffix == ".flac":
        return header.startswith(b"fLaC")
    if suffix == ".ogg":
        return header.startswith(b"OggS")
    return False


async def save_video(
    upload: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
) -> SavedUpload:
    destination.parent.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    total = 0
    header = bytearray()

    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="视频文件超过大小限制",
                    )
                if len(header) < 32:
                    header.extend(chunk[: 32 - len(header)])
                digest.update(chunk)
                check_disk_space(destination.parent, len(chunk))
                output.write(chunk)

        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="视频文件为空",
            )
        if not looks_like_video(bytes(header), destination.suffix):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="文件内容不是有效的受支持视频容器",
            )
        return SavedUpload(destination, total, digest.hexdigest())
    except Exception:
        shutil.rmtree(destination.parent, ignore_errors=True)
        raise
    finally:
        await upload.close()


# Compatibility alias for callers and integrations that still use the old name.
save_mp4 = save_video


async def save_audio(
    upload: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
) -> SavedUpload:
    destination.parent.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    total = 0
    header = bytearray()
    suffix = destination.suffix.lower()

    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="音频文件超过大小限制",
                    )
                if len(header) < 32:
                    header.extend(chunk[: 32 - len(header)])
                digest.update(chunk)
                check_disk_space(destination.parent, len(chunk))
                output.write(chunk)

        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="音频文件为空",
            )
        if not looks_like_audio(bytes(header), suffix):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="文件内容不是受支持的音频格式",
            )
        return SavedUpload(destination, total, digest.hexdigest())
    except Exception:
        shutil.rmtree(destination.parent, ignore_errors=True)
        raise
    finally:
        await upload.close()


async def save_lyrics(
    *,
    lyrics_text: str | None,
    lyrics_file: UploadFile | None,
    destination: Path,
    max_bytes: int,
) -> str | None:
    text = lyrics_text.strip() if lyrics_text else ""
    if text and lyrics_file is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="歌词文本和歌词文件只能选择一种",
        )

    source: str | None = None
    if lyrics_file is not None:
        try:
            raw = await lyrics_file.read(max_bytes + 1)
        finally:
            await lyrics_file.close()
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="歌词文件超过大小限制",
            )
        try:
            text = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="歌词文件必须使用 UTF-8 编码",
            ) from exc
        source = "file"
    elif text:
        source = "text"

    if not text:
        return None
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="歌词文本超过大小限制",
        )
    destination.write_text(text + "\n", encoding="utf-8")
    return source
