from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any, Callable

from app.video.audio import AudioExtractionError


DEFAULT_MDX_MODEL = "UVR_MDXNET_KARA_2.onnx"


class MDXNetVocalRemover:
    """Generate an instrumental stem with an MDX-Net UVR model."""

    def __init__(
        self,
        *,
        model_dir: Path,
        model_filename: str = DEFAULT_MDX_MODEL,
        separator_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.model_filename = model_filename
        self._separator_factory = separator_factory
        self._lock = threading.Lock()

    def _create_separator(
        self,
        output_dir: Path,
        *,
        output_single_stem: str | None = "Instrumental",
    ) -> Any:
        factory = self._separator_factory
        if factory is None:
            try:
                from audio_separator.separator import Separator
            except ImportError as exc:
                raise AudioExtractionError(
                    "MDX-Net vocal removal is not installed"
                ) from exc
            factory = Separator

        self.model_dir.mkdir(parents=True, exist_ok=True)
        separator = factory(
            model_file_dir=str(self.model_dir),
            output_dir=str(output_dir),
            output_format="WAV",
            output_single_stem=output_single_stem,
        )
        separator.load_model(model_filename=self.model_filename)
        return separator

    def remove_vocals(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                output_path.unlink(missing_ok=True)
                separator = self._create_separator(
                    output_path.parent
                )
                output_files = separator.separate(
                    str(input_path),
                    {"Instrumental": output_path.stem},
                )
                self._place_output(output_files, output_path)
        except AudioExtractionError:
            raise
        except Exception as exc:
            raise AudioExtractionError(
                "MDX-Net vocal removal failed"
            ) from exc

    def separate_stems(
        self,
        input_path: Path,
        vocals_path: Path,
        instrumental_path: Path,
    ) -> None:
        if vocals_path.parent.resolve() != instrumental_path.parent.resolve():
            raise ValueError("Separated stems must share an output directory")
        vocals_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                vocals_path.unlink(missing_ok=True)
                instrumental_path.unlink(missing_ok=True)
                separator = self._create_separator(
                    vocals_path.parent,
                    output_single_stem=None,
                )
                output_files = separator.separate(
                    str(input_path),
                    {
                        "Vocals": vocals_path.stem,
                        "Instrumental": instrumental_path.stem,
                    },
                )
                self._place_output(output_files, vocals_path)
                self._place_output(output_files, instrumental_path)
        except AudioExtractionError:
            raise
        except Exception as exc:
            raise AudioExtractionError(
                "MDX-Net stem separation failed"
            ) from exc

    @staticmethod
    def _place_output(
        output_files: list[str],
        output_path: Path,
    ) -> None:
        if output_path.is_file() and output_path.stat().st_size > 0:
            return

        for filename in output_files:
            candidate = Path(filename)
            if not candidate.is_absolute():
                candidate = output_path.parent / candidate
            if not candidate.is_file() or candidate.stat().st_size == 0:
                continue
            if candidate.resolve() != output_path.resolve():
                shutil.move(str(candidate), str(output_path))
            return

        raise AudioExtractionError(
            "MDX-Net vocal removal produced an empty output"
        )
