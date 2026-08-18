from __future__ import annotations

import json
import logging
import re
import time
import traceback
from datetime import UTC, datetime
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMA_VERSION = 1
MAX_DETAIL_TEXT = 4_000
REDACTED = "[REDACTED]"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|password|secret|token|signature|credential)",
    re.IGNORECASE,
)
_PATH_KEY = re.compile(r"(^|_)(path|file|directory|dir)$", re.IGNORECASE)
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_INLINE_SECRET = re.compile(
    r"(?i)\b(token|api[_-]?key|password|secret|signature|credential)"
    r"\s*[=:]\s*[^\s,;]+"
)
_WINDOWS_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/])(?:[^\\/\r\n\"']+[\\/])*([^\\/\r\n\"']+)"
)
_UNIX_PATH = re.compile(r"(?<!:)(?:/(?:[^/\s\"']+)){2,}")
_URL_SECRET = re.compile(r"(?i)(token|key|signature|credential|password|secret)")
_context: ContextVar[dict[str, Any]] = ContextVar("event_log_context", default={})


def _truncate(value: str, limit: int = MAX_DETAIL_TEXT) -> str:
    if len(value) <= limit:
        return value
    return f"{value[-limit:]}\n...[truncated]"


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return value
        query = urlencode(
            [
                (key, REDACTED if _URL_SECRET.search(key) else item)
                for key, item in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except ValueError:
        return value


def sanitize_command(command: Any) -> list[str] | str:
    if not isinstance(command, (list, tuple)):
        return _truncate(_BEARER.sub(r"\1[REDACTED]", str(command)))
    sanitized: list[str] = []
    hide_next = False
    for raw in command:
        value = str(raw)
        lower = value.lower()
        if hide_next:
            sanitized.append(REDACTED)
            hide_next = False
            continue
        if lower in {"-headers", "--header", "-authorization", "--token", "--api-key"}:
            sanitized.append(value)
            hide_next = True
            continue
        if _BEARER.search(value) or _SECRET_KEY.search(value.split("=", 1)[0]):
            sanitized.append(REDACTED)
        elif Path(value).is_absolute():
            sanitized.append(Path(value).name)
        else:
            sanitized.append(_truncate(_safe_url(value)))
    return sanitized


def sanitize_details(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return value.name
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_details(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        if key.lower() in {"command", "cmd", "argv", "args"}:
            return sanitize_command(value)
        return [sanitize_details(item, key=key) for item in value]
    text = str(value)
    if _PATH_KEY.search(key) or Path(text).is_absolute():
        return Path(text).name
    text = _BEARER.sub(r"\1[REDACTED]", _safe_url(text))
    text = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    if key.lower() in {
        "traceback",
        "error_summary",
        "stderr_tail",
        "stdout_tail",
        "diagnostic",
    }:
        text = _WINDOWS_PATH.sub(lambda match: f"<path>/{match.group(1)}", text)
        text = _UNIX_PATH.sub("<path>", text)
    return _truncate(text)


def exception_details(error: BaseException, *, include_traceback: bool = True) -> dict[str, Any]:
    details: dict[str, Any] = {
        "exception_type": type(error).__name__,
        "error_summary": _truncate(str(error), 1_000),
    }
    if include_traceback:
        details["traceback"] = _truncate(
            "".join(traceback.format_exception(error)),
            MAX_DETAIL_TEXT,
        )
    for attribute in (
        "exit_code",
        "timeout_seconds",
        "stderr_tail",
        "stdout_tail",
        "command",
    ):
        value = getattr(error, attribute, None)
        if value is not None:
            details[attribute] = value
    return sanitize_details(details)


@contextmanager
def event_context(**values: Any) -> Iterator[None]:
    current = dict(_context.get())
    current.update({key: value for key, value in values.items() if value is not None})
    token = _context.set(current)
    try:
        yield
    finally:
        _context.reset(token)


def current_event_context() -> dict[str, Any]:
    return dict(_context.get())


class StructuredEventLogger:
    def __init__(
        self,
        *,
        database: Any,
        event_log_level: str = "INFO",
        debug_enabled: bool = False,
        json_console: bool = False,
        console_level: str = "INFO",
        progress_throttle_seconds: float = 5.0,
        console_logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.event_log_level = event_log_level.upper()
        self.debug_enabled = debug_enabled
        self.json_console = json_console
        self.console_level = console_level.upper()
        self.progress_throttle_seconds = progress_throttle_seconds
        self.console_logger = console_logger or logging.getLogger("nicokara.events")
        self.console_logger.setLevel(_LEVELS.get(self.console_level, logging.INFO))
        self._last_progress: dict[tuple[Any, ...], float] = {}
        self._progress_lock = Lock()

    def _level_enabled(self, level: str, threshold: str) -> bool:
        normalized = level.upper()
        if normalized == "DEBUG" and not self.debug_enabled:
            return False
        return _LEVELS.get(normalized, 20) >= _LEVELS.get(threshold, 20)

    def emit(
        self,
        *,
        event: str,
        level: str,
        category: str,
        message: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        component: str | None = None,
        duration_ms: float | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        normalized = level.upper()
        persist_enabled = self._level_enabled(normalized, self.event_log_level)
        console_enabled = self._level_enabled(normalized, self.console_level)
        if not persist_enabled and not console_enabled:
            return False
        context = current_event_context()
        resolved_reference_id = reference_id or job_id or context.get("job_id")
        record = {
            "event": event,
            "level": normalized,
            "category": category.lower(),
            "message": sanitize_details(message, key="message"),
            "reference_type": reference_type or ("job" if resolved_reference_id else None),
            "reference_id": resolved_reference_id,
            "run_id": run_id or context.get("run_id"),
            "stage": stage or context.get("stage"),
            "component": component or context.get("component"),
            "duration_ms": round(duration_ms, 3) if duration_ms is not None else None,
            "request_id": request_id or context.get("request_id"),
            "schema_version": SCHEMA_VERSION,
            "details": sanitize_details(details or {}),
        }
        console_record = {
            **record,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if console_enabled:
            if self.json_console:
                output = json.dumps(
                    console_record,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self.console_logger.log(_LEVELS.get(normalized, 20), output)
            else:
                self.console_logger.log(
                    _LEVELS.get(normalized, 20), "%s: %s", event, message
                )
        if not persist_enabled:
            return True
        try:
            self.database._insert_event_log(**record)
        except Exception as exc:
            self.console_logger.error(
                "Event log persistence failed for %s (%s)",
                event,
                type(exc).__name__,
            )
            return False
        return True

    def progress(
        self,
        *,
        event: str,
        category: str,
        message: str,
        progress: int | float,
        reference_id: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        component: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        context = current_event_context()
        key = (
            event,
            reference_id or context.get("job_id"),
            run_id or context.get("run_id"),
            stage or context.get("stage"),
            component or context.get("component"),
        )
        now = time.monotonic()
        with self._progress_lock:
            previous = self._last_progress.get(key)
            if previous is not None and now - previous < self.progress_throttle_seconds:
                return False
            self._last_progress[key] = now
        payload = dict(details or {})
        payload["progress"] = progress
        return self.emit(
            event=event,
            level="INFO",
            category=category,
            message=message,
            reference_id=reference_id,
            run_id=run_id,
            stage=stage,
            component=component,
            details=payload,
        )

    def stage(
        self,
        *,
        job_id: str,
        run_id: str,
        stage: str,
        component: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> "StageTrace":
        return StageTrace(
            recorder=self,
            job_id=job_id,
            run_id=run_id,
            stage=stage,
            component=component,
            message=message,
            details=details or {},
        )


class StageTrace:
    def __init__(self, *, recorder: StructuredEventLogger, job_id: str, run_id: str,
                 stage: str, component: str, message: str, details: dict[str, Any]) -> None:
        self.recorder = recorder
        self.job_id = job_id
        self.run_id = run_id
        self.stage = stage
        self.component = component
        self.message = message
        self.details = details
        self.output_details: dict[str, Any] = {}
        self.started = 0.0
        self._context_manager = None

    def __enter__(self) -> "StageTrace":
        self.started = time.perf_counter()
        self._context_manager = event_context(
            job_id=self.job_id, run_id=self.run_id,
            stage=self.stage, component=self.component,
        )
        self._context_manager.__enter__()
        self.recorder.emit(
            event="stage.started", level="INFO", category="pipeline",
            message=f"开始{self.message}", details=self.details,
        )
        return self

    def result(self, **details: Any) -> None:
        self.output_details.update(details)

    def fallback(self, *, reason: str, **details: Any) -> None:
        self.recorder.emit(
            event="stage.fallback", level="WARNING", category="pipeline",
            message=f"{self.message}启用降级路径",
            details={"reason": reason, **details},
        )

    def skipped(self, *, reason: str, **details: Any) -> None:
        self.recorder.emit(
            event="stage.skipped", level="INFO", category="pipeline",
            message=f"跳过{self.message}", details={"reason": reason, **details},
        )

    def __exit__(self, error_type, error, error_traceback) -> bool:
        duration_ms = (time.perf_counter() - self.started) * 1000
        if error is None:
            self.recorder.emit(
                event="stage.completed", level="INFO", category="pipeline",
                message=f"{self.message}完成", duration_ms=duration_ms,
                details=self.output_details,
            )
        else:
            self.recorder.emit(
                event="stage.failed", level="ERROR", category="pipeline",
                message=f"{self.message}失败", duration_ms=duration_ms,
                details=exception_details(error),
            )
        if self._context_manager is not None:
            self._context_manager.__exit__(error_type, error, error_traceback)
        return False
