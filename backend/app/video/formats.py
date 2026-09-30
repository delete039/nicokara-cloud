from __future__ import annotations

from pathlib import Path


# These are containers that FFmpeg can demux reliably in the server runtime.
# Keep the list aligned with frontend/lib/video-formats.ts.
VIDEO_MIME_TYPES: dict[str, tuple[str, ...]] = {
    ".mp4": ("video/mp4",),
    ".m4v": ("video/x-m4v", "video/mp4"),
    ".mov": ("video/quicktime",),
    ".3gp": ("video/3gpp",),
    ".3g2": ("video/3gpp2",),
    ".mkv": ("video/x-matroska",),
    ".webm": ("video/webm",),
    ".avi": ("video/x-msvideo", "video/avi"),
    ".wmv": ("video/x-ms-wmv",),
    ".asf": ("video/x-ms-asf",),
    ".flv": ("video/x-flv",),
    ".f4v": ("video/x-f4v",),
    ".mpeg": ("video/mpeg",),
    ".mpg": ("video/mpeg",),
    ".mpe": ("video/mpeg",),
    ".m2v": ("video/mpeg",),
    ".ts": ("video/mp2t",),
    ".mts": ("video/mp2t",),
    ".m2ts": ("video/mp2t",),
    ".vob": ("video/mpeg",),
    ".ogv": ("video/ogg",),
}

SUPPORTED_VIDEO_SUFFIXES = frozenset(VIDEO_MIME_TYPES)


def video_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in SUPPORTED_VIDEO_SUFFIXES else ""


def is_supported_video_name(filename: str | None) -> bool:
    return bool(video_suffix(filename))


def video_input_filename(filename: str | None) -> str:
    """Return a stable job-local input name while preserving the container."""
    suffix = video_suffix(filename) or ".mp4"
    return f"input{suffix}"


def looks_like_video(header: bytes, suffix: str) -> bool:
    """Perform a cheap container signature check before handing data to FFmpeg."""
    suffix = suffix.lower()
    if suffix in {".mp4", ".m4v", ".mov", ".3gp", ".3g2", ".f4v"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if suffix in {".mkv", ".webm"}:
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if suffix == ".avi":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    if suffix in {".wmv", ".asf"}:
        return header.startswith(bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C"))
    if suffix == ".flv":
        return header.startswith(b"FLV")
    if suffix == ".ogv":
        return header.startswith(b"OggS")
    if suffix in {".ts", ".mts", ".m2ts"}:
        return any(
            len(header) > offset and header[offset] == 0x47
            for offset in (0, 4, 188, 192, 376, 380)
        )
    if suffix in {".mpeg", ".mpg", ".mpe", ".m2v", ".vob"}:
        return any(
            header.startswith(marker)
            for marker in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xbb", b"\x00\x00\x01\xb3")
        )
    return False


def supported_video_accept() -> str:
    mime_types = sorted({mime for values in VIDEO_MIME_TYPES.values() for mime in values})
    extensions = sorted(SUPPORTED_VIDEO_SUFFIXES)
    return ",".join([*mime_types, *extensions])


def supported_video_label() -> str:
    return "MP4、MOV、M4V、MKV、WebM、AVI、WMV、FLV、MPEG、TS、3GP、OGV"
