from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ALLOWED_ORIGINS = ",".join(
    (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    )
)
DEFAULT_WORKER_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "workers.toml"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NICOKARA_",
        extra="ignore",
    )

    app_name: str = "ニコカラ自动生成器 API"
    api_prefix: str = "/api/v1"
    data_dir: Path = Field(default=Path("data"))
    storage_dir: Path = Field(default=Path("../storage/jobs"))
    max_video_bytes: int = 1024 * 1024 * 1024
    max_audio_bytes: int = 256 * 1024 * 1024
    max_lyrics_bytes: int = 1024 * 1024
    max_pending_jobs: int = 4
    max_active_jobs_per_client: int = 2
    max_upload_slots: int = 1
    upload_ticket_timeout_seconds: int = 120
    upload_ticket_upload_timeout_seconds: int = 3600
    worker_config_path: Path = Field(default=DEFAULT_WORKER_CONFIG_PATH)
    worker_heartbeat_interval_seconds: float = 5
    cleanup_enabled: bool = True
    job_retention_hours: int = 24
    cleanup_interval_seconds: int = 3600
    log_level: str = "INFO"
    event_log_level: str = "INFO"
    json_console_logs: bool = False
    event_log_debug: bool = False
    event_log_retention_days: int = 30
    event_log_max_rows: int = 100_000
    event_log_progress_throttle_seconds: float = 5.0
    allowed_origins: str = DEFAULT_ALLOWED_ORIGINS
    trusted_proxy_hosts: str = "127.0.0.1,::1"
    processing_enabled: bool = True
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_seconds: int = 900
    video_render_timeout_seconds: int = 7200
    video_render_preset: str = "veryfast"
    video_render_crf: int = 20
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    fa_kara_enabled: bool = True
    fa_kara_device: str = "auto"
    fa_kara_timeout_seconds: int = 600
    fa_kara_min_confidence: float = 0.15
    fa_kara_max_concurrent_alignments: int = 1
    fa_kara_audio_speed: float = 1.0
    fa_kara_silence_window_seconds: float = 0.8
    fa_kara_silence_top_percent: float = 10.0
    fa_kara_silence_threshold_ratio: float = 0.1
    fa_kara_tail_window_seconds: float = 0.02
    vocal_removal_backend: str = "mdx"
    vocal_removal_model: str = "UVR_MDXNET_KARA_2.onnx"
    vocal_removal_model_dir: Path = Field(
        default=Path("data/audio-separator-models")
    )
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 60
    admin_token: SecretStr | None = None

    @field_validator("deepseek_api_key", "admin_token", mode="before")
    @classmethod
    def empty_secret_is_disabled(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "max_video_bytes",
        "max_audio_bytes",
        "max_lyrics_bytes",
        "max_pending_jobs",
        "max_active_jobs_per_client",
        "max_upload_slots",
        "upload_ticket_timeout_seconds",
        "upload_ticket_upload_timeout_seconds",
        "job_retention_hours",
        "cleanup_interval_seconds",
        "event_log_retention_days",
        "event_log_max_rows",
        "video_render_timeout_seconds",
        "fa_kara_timeout_seconds",
        "fa_kara_max_concurrent_alignments",
    )
    @classmethod
    def positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator(
        "worker_heartbeat_interval_seconds",
        "fa_kara_audio_speed",
        "fa_kara_silence_window_seconds",
        "fa_kara_silence_threshold_ratio",
        "fa_kara_tail_window_seconds",
        "event_log_progress_throttle_seconds",
    )
    @classmethod
    def positive_heartbeat_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("fa_kara_silence_top_percent")
    @classmethod
    def valid_fa_kara_percent(cls, value: float) -> float:
        if not 0 < value <= 100:
            raise ValueError("must be greater than zero and at most 100")
        return value

    @field_validator("fa_kara_min_confidence")
    @classmethod
    def valid_fa_kara_confidence(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("must be between zero and one")
        return value

    @field_validator("video_render_crf")
    @classmethod
    def valid_crf(cls, value: int) -> int:
        if not 0 <= value <= 51:
            raise ValueError("must be between 0 and 51")
        return value

    @field_validator("log_level", "event_log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        return normalized

    @field_validator("video_render_preset")
    @classmethod
    def valid_video_preset(cls, value: str) -> str:
        allowed = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
        if value not in allowed:
            raise ValueError("unsupported x264 preset")
        return value

    @field_validator("vocal_removal_backend")
    @classmethod
    def valid_vocal_removal_backend(cls, value: str) -> str:
        if value not in {"mdx", "stft"}:
            raise ValueError("must be mdx or stft")
        return value

    @field_validator("fa_kara_device")
    @classmethod
    def valid_fa_kara_device(cls, value: str) -> str:
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("must be auto, cpu or cuda")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nicokara.sqlite3"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def trusted_proxies(self) -> tuple[str, ...]:
        return tuple(
            host.strip()
            for host in self.trusted_proxy_hosts.split(",")
            if host.strip()
        )

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
