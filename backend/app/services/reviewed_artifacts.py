from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, UploadFile, status

from app.alignment.models import LyricTimeline
from app.alignment.review import TimelineReviewError, lyric_timeline_from_dict
from app.lyrics.models import LyricDocument, lyric_document_from_dict


ReviewedArtifactKind = Literal["lyrics", "timeline", "subtitle"]


class ReviewedArtifactError(ValueError):
    """Raised when a file is not a supported Nicokara reviewed artifact."""


@dataclass(frozen=True)
class ReviewedArtifact:
    kind: ReviewedArtifactKind
    lyrics: LyricDocument | None = None
    timeline: LyricTimeline | None = None
    subtitle: str | None = None


@dataclass(frozen=True)
class SavedReviewedArtifacts:
    lyrics_path: Path | None = None
    timeline_path: Path | None = None
    subtitle_path: Path | None = None
    lyrics: LyricDocument | None = None
    timeline: LyricTimeline | None = None

    @property
    def has_any(self) -> bool:
        return any((self.lyrics_path, self.timeline_path, self.subtitle_path))

    @property
    def source_name(self) -> str | None:
        if self.timeline_path is not None:
            return "reviewed_timeline"
        if self.lyrics_path is not None:
            return "reviewed_lyrics"
        if self.subtitle_path is not None:
            return "reviewed_subtitle"
        return None

    def derived_lyrics_text(self) -> str | None:
        if self.lyrics is not None:
            return self.lyrics.source_text.strip() or None
        if self.timeline is not None:
            text = "\n".join(line.surface for line in self.timeline.lines).strip()
            return text or None
        return None


def _decode_utf8(filename: str, raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReviewedArtifactError(
            f"{filename} 必须使用 UTF-8 编码"
        ) from exc
    if not text.strip():
        raise ReviewedArtifactError(f"{filename} 是空文件")
    if "\x00" in text:
        raise ReviewedArtifactError(f"{filename} 包含无效字符")
    return text


def _looks_like_subtitle(text: str) -> bool:
    return "[Script Info]" in text and "[Events]" in text


def _parse_subtitle(filename: str, text: str) -> ReviewedArtifact:
    required = ("[Script Info]", "[V4+ Styles]", "[Events]", "Dialogue:")
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise ReviewedArtifactError(
            f"{filename} 不是本站导出的完整 ASS 字幕，缺少 {missing[0]}"
        )
    return ReviewedArtifact(kind="subtitle", subtitle=text)


def _validate_lyrics(filename: str, value: dict) -> LyricDocument:
    try:
        document = lyric_document_from_dict(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewedArtifactError(
            f"{filename} 不是有效的调整后注音数据"
        ) from exc
    if not document.lines:
        raise ReviewedArtifactError(f"{filename} 的注音数据不包含歌词行")
    for line_index, line in enumerate(document.lines, start=1):
        if not line.surface or not line.tokens:
            raise ReviewedArtifactError(
                f"{filename} 第 {line_index} 行缺少歌词或注音 token"
            )
    return document


def _validate_timeline(filename: str, value: dict) -> LyricTimeline:
    try:
        timeline = lyric_timeline_from_dict(value)
    except TimelineReviewError as exc:
        raise ReviewedArtifactError(
            f"{filename} 不是有效的调整后时间轴"
        ) from exc
    if not timeline.lines:
        raise ReviewedArtifactError(f"{filename} 的时间轴不包含歌词行")

    previous_line_end = 0
    for line_index, line in enumerate(timeline.lines, start=1):
        if (
            line.start_ms < previous_line_end
            or line.end_ms <= line.start_ms
            or not line.tokens
        ):
            raise ReviewedArtifactError(
                f"{filename} 第 {line_index} 行时间范围无效"
            )
        previous_token_end = line.start_ms
        for token_index, token in enumerate(line.tokens, start=1):
            if (
                token.start_ms < previous_token_end
                or token.start_ms < line.start_ms
                or token.end_ms > line.end_ms
                or token.end_ms < token.start_ms
            ):
                raise ReviewedArtifactError(
                    f"{filename} 第 {line_index} 行第 {token_index} 个词时间无效"
                )
            previous_mora_end = token.start_ms
            for mora_index, mora in enumerate(token.moras, start=1):
                if (
                    mora.start_ms < previous_mora_end
                    or mora.start_ms < token.start_ms
                    or mora.end_ms > token.end_ms
                    or mora.end_ms <= mora.start_ms
                ):
                    raise ReviewedArtifactError(
                        f"{filename} 第 {line_index} 行第 {token_index} 个词的 "
                        f"mora {mora_index} 时间无效"
                    )
                previous_mora_end = mora.end_ms
            previous_token_end = token.end_ms
        previous_line_end = line.end_ms
    return timeline


def classify_reviewed_artifact(filename: str, raw: bytes) -> ReviewedArtifact:
    """Recognize current Nicokara exports by content, not by their filename."""

    text = _decode_utf8(filename, raw)
    if filename.lower().endswith(".ass") or _looks_like_subtitle(text):
        return _parse_subtitle(filename, text)

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewedArtifactError(
            f"{filename} 不是本站导出的 JSON 或 ASS 文件"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewedArtifactError(f"{filename} 不是本站导出的对象格式")

    if "confidence" in value and isinstance(value.get("lines"), list):
        return ReviewedArtifact(
            kind="timeline",
            timeline=_validate_timeline(filename, value),
        )
    if "provider" in value and "source_text" in value:
        return ReviewedArtifact(
            kind="lyrics",
            lyrics=_validate_lyrics(filename, value),
        )
    raise ReviewedArtifactError(
        f"{filename} 不是本站导出的调整后注音、mora 时间轴或 ASS 字幕"
    )


async def save_reviewed_artifacts(
    uploads: list[UploadFile] | None,
    destination_dir: Path,
    *,
    max_bytes: int,
) -> SavedReviewedArtifacts:
    if not uploads:
        return SavedReviewedArtifacts()
    if len(uploads) > 3:
        for upload in uploads:
            await upload.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="一次最多导入三个本站调整数据文件",
        )

    destination_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[ReviewedArtifactKind, ReviewedArtifact] = {}
    try:
        for upload in uploads:
            filename = Path(upload.filename or "artifact").name
            try:
                raw = await upload.read(max_bytes + 1)
            finally:
                await upload.close()
            if len(raw) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"{filename} 超过调整数据大小限制",
                )
            try:
                artifact = classify_reviewed_artifact(filename, raw)
            except ReviewedArtifactError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc
            if artifact.kind in artifacts:
                label = {
                    "lyrics": "注音",
                    "timeline": "时间轴",
                    "subtitle": "ASS 字幕",
                }[artifact.kind]
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"检测到重复的{label}文件",
                )
            artifacts[artifact.kind] = artifact
    finally:
        for upload in uploads:
            await upload.close()

    lyrics_path = None
    timeline_path = None
    subtitle_path = None
    if lyrics_artifact := artifacts.get("lyrics"):
        lyrics_path = destination_dir / "imported_lyrics_processed.json"
        lyrics_path.write_text(
            json.dumps(
                lyrics_artifact.lyrics.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if timeline_artifact := artifacts.get("timeline"):
        timeline_path = destination_dir / "imported_timeline.json"
        timeline_path.write_text(
            json.dumps(
                timeline_artifact.timeline.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if subtitle_artifact := artifacts.get("subtitle"):
        subtitle_path = destination_dir / "imported_subtitle.ass"
        subtitle_path.write_text(
            subtitle_artifact.subtitle or "",
            encoding="utf-8-sig",
        )
    return SavedReviewedArtifacts(
        lyrics_path=lyrics_path,
        timeline_path=timeline_path,
        subtitle_path=subtitle_path,
        lyrics=artifacts.get("lyrics").lyrics if artifacts.get("lyrics") else None,
        timeline=(
            artifacts.get("timeline").timeline
            if artifacts.get("timeline")
            else None
        ),
    )


def ensure_lyrics_source_from_reviewed_artifacts(
    saved: SavedReviewedArtifacts,
    lyrics_path: Path,
    lyrics_source: str | None,
) -> tuple[str | None, Path | None]:
    if lyrics_source is not None:
        return lyrics_source, lyrics_path
    derived = saved.derived_lyrics_text()
    if derived:
        lyrics_path.write_text(derived + "\n", encoding="utf-8")
        return saved.source_name, lyrics_path
    if saved.has_any:
        return saved.source_name, None
    return None, None
