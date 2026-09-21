from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.processing_control import check_interrupted, run_process
from app.alignment.mms import (
    MMSForcedAligner,
    MMSMoraSpan,
    ForcedAlignmentError,
)


YOHANE_MODEL_NAME = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
# A single mora lasting this long is a strong signal that the CTC path latched
# onto an unrelated earlier acoustic match. Keep the broader MMS limit intact.
YOHANE_MAX_MORA_DURATION_MS = 8_000
YohaneMoraSpan = MMSMoraSpan


class SubprocessYohaneRuntime:
    """Run the opt-in Yohane model in a killable, one-task subprocess."""

    def __init__(
        self,
        *,
        source_dir: Path,
        model_dir: Path,
        device: str = "auto",
        runner: Any = run_process,
        python_command: str = sys.executable,
        audio_speed: float = 1.0,
        limiter: Any | None = None,
    ) -> None:
        self.source_dir = Path(source_dir)
        self.model_dir = Path(model_dir)
        self.device = device
        self.runner = runner
        self.python_command = python_command
        self.audio_speed = audio_speed
        self.limiter = limiter or threading.BoundedSemaphore(1)

    def align(
        self,
        audio_path: Path,
        tokens: list[str],
        timeout_seconds: float,
        *,
        line_token_counts: list[int],
    ) -> list[YohaneMoraSpan]:
        request_id = uuid.uuid4().hex
        request_path = audio_path.parent / f".yohane-{request_id}.request.json"
        output_path = audio_path.parent / f".yohane-{request_id}.output.json"
        request_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path.resolve()),
                    "tokens": tokens,
                    "line_token_counts": line_token_counts,
                    "audio_speed": self.audio_speed,
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        command = [
            self.python_command,
            str(Path(__file__).with_name("yohane_worker.py")),
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--source-dir",
            str(self.source_dir.resolve()),
            "--model-dir",
            str(self.model_dir.resolve()),
            "--device",
            self.device,
        ]
        try:
            while not self.limiter.acquire(timeout=0.1):
                check_interrupted()
            try:
                check_interrupted()
                self.runner(
                    command,
                    timeout=timeout_seconds,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            finally:
                self.limiter.release()
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            spans = [
                YohaneMoraSpan(
                    int(span["start_ms"]),
                    int(span["end_ms"]),
                    float(span["score"]),
                )
                for span in payload["spans"]
            ]
            if len(spans) != len(tokens):
                raise ForcedAlignmentError(
                    "Yohane returned a different number of mora spans than tokens"
                )
            return spans
        except subprocess.TimeoutExpired as exc:
            raise ForcedAlignmentError(
                "Yohane alignment timed out",
                timeout_seconds=timeout_seconds,
                stderr_tail=str(exc.stderr or "")[-1200:],
                command=command,
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            detail = detail[-1200:] if detail else ""
            message = "Yohane worker failed"
            if detail:
                message += f": {detail}"
            raise ForcedAlignmentError(
                message,
                exit_code=exc.returncode,
                stderr_tail=detail,
                command=command,
            ) from exc
        except ForcedAlignmentError:
            raise
        except Exception as exc:
            raise ForcedAlignmentError("Yohane worker failed") from exc
        finally:
            request_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


class YohaneForcedAligner(MMSForcedAligner):
    """Yohane CTC spans mapped through the same reviewed mora contract as MMS."""

    requires_vocals = True
    alignment_model = YOHANE_MODEL_NAME

    def __init__(
        self,
        *,
        runtime: Any,
        timeout_seconds: float = 900,
        min_confidence: float = 0.10,
        max_mora_duration_ms: int = YOHANE_MAX_MORA_DURATION_MS,
    ) -> None:
        super().__init__(
            runtime=runtime,
            timeout_seconds=timeout_seconds,
            min_confidence=min_confidence,
            max_mora_duration_ms=max_mora_duration_ms,
        )

    def align(self, lyrics, transcript, *, audio_path):
        timeline = super().align(lyrics, transcript, audio_path=audio_path)
        from dataclasses import replace

        return replace(
            timeline,
            alignment_engine="fa_kara_yohane",
            alignment_model=YOHANE_MODEL_NAME,
            warnings=[
                warning.replace("mms_low_confidence", "yohane_low_confidence", 1)
                for warning in timeline.warnings
            ],
        )
