from __future__ import annotations

from pathlib import Path

import pytest

from app.video.audio import AudioExtractionError
from app.vocal.mdx import MDXNetVocalRemover


class FakeSeparator:
    def __init__(self, **kwargs) -> None:
        self.init_kwargs = kwargs
        self.output_dir = kwargs["output_dir"]
        self.loaded_models: list[str] = []
        self.separations: list[tuple[str, dict[str, str]]] = []

    def load_model(self, *, model_filename: str) -> None:
        self.loaded_models.append(model_filename)

    def separate(
        self,
        input_path: str,
        output_names: dict[str, str],
    ) -> list[str]:
        self.separations.append((input_path, output_names))
        output_path = (
            Path(self.output_dir)
            / f"{output_names['Instrumental']}.wav"
        )
        output_path.write_bytes(b"instrumental audio")
        return [str(output_path)]


def test_mdx_net_generates_named_instrumental_wav(
    tmp_path: Path,
) -> None:
    created: list[FakeSeparator] = []

    def separator_factory(**kwargs) -> FakeSeparator:
        separator = FakeSeparator(**kwargs)
        created.append(separator)
        return separator

    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"input audio")
    output_path = tmp_path / "job" / "audio_instrumental.wav"

    remover = MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=separator_factory,
    )
    remover.remove_vocals(input_path, output_path)

    assert output_path.read_bytes() == b"instrumental audio"
    assert created[0].init_kwargs == {
        "model_file_dir": str(tmp_path / "models"),
        "output_dir": str(output_path.parent),
        "output_format": "WAV",
        "output_single_stem": "Instrumental",
    }
    assert created[0].loaded_models == ["UVR_MDXNET_KARA_2.onnx"]
    assert created[0].separations == [
        (
            str(input_path),
            {"Instrumental": "audio_instrumental"},
        )
    ]


def test_mdx_net_separates_vocals_and_instrumental_in_one_inference(
    tmp_path: Path,
) -> None:
    created: list[FakeSeparator] = []

    class DualStemSeparator(FakeSeparator):
        def separate(
            self,
            input_path: str,
            output_names: dict[str, str],
        ) -> list[str]:
            self.separations.append((input_path, output_names))
            outputs = []
            for stem, content in (
                ("Vocals", b"isolated vocals"),
                ("Instrumental", b"instrumental audio"),
            ):
                path = Path(self.output_dir) / f"{output_names[stem]}.wav"
                path.write_bytes(content)
                outputs.append(str(path))
            return outputs

    def separator_factory(**kwargs) -> DualStemSeparator:
        separator = DualStemSeparator(**kwargs)
        created.append(separator)
        return separator

    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"input audio")
    vocals_path = tmp_path / "job" / "audio_vocals.wav"
    instrumental_path = tmp_path / "job" / "audio_instrumental.wav"

    MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=separator_factory,
    ).separate_stems(input_path, vocals_path, instrumental_path)

    assert vocals_path.read_bytes() == b"isolated vocals"
    assert instrumental_path.read_bytes() == b"instrumental audio"
    assert created[0].init_kwargs == {
        "model_file_dir": str(tmp_path / "models"),
        "output_dir": str(vocals_path.parent),
        "output_format": "WAV",
        "output_single_stem": None,
    }
    assert created[0].separations == [
        (
            str(input_path),
            {
                "Vocals": "audio_vocals",
                "Instrumental": "audio_instrumental",
            },
        )
    ]


def test_mdx_net_isolates_separator_output_for_each_job(
    tmp_path: Path,
) -> None:
    created: list[FakeSeparator] = []

    def separator_factory(**kwargs) -> FakeSeparator:
        separator = FakeSeparator(**kwargs)
        created.append(separator)
        return separator

    remover = MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=separator_factory,
    )
    for job_name in ("first", "second"):
        input_path = tmp_path / f"{job_name}.wav"
        input_path.write_bytes(b"input")
        remover.remove_vocals(
            input_path,
            tmp_path / job_name / "audio_instrumental.wav",
        )

    assert len(created) == 2
    assert [
        separator.init_kwargs["output_dir"]
        for separator in created
    ] == [
        str(tmp_path / "first"),
        str(tmp_path / "second"),
    ]
    assert all(
        separator.loaded_models == ["UVR_MDXNET_KARA_2.onnx"]
        for separator in created
    )


def test_mdx_net_replaces_stale_output_from_an_earlier_attempt(
    tmp_path: Path,
) -> None:
    class RenamingSeparator(FakeSeparator):
        def separate(
            self,
            input_path: str,
            output_names: dict[str, str],
        ) -> list[str]:
            fresh_output = Path(self.output_dir) / "generated.wav"
            fresh_output.write_bytes(b"fresh instrumental")
            return [str(fresh_output)]

    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"input")
    output_path = tmp_path / "job" / "audio_instrumental.wav"
    output_path.parent.mkdir()
    output_path.write_bytes(b"stale instrumental")

    MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=RenamingSeparator,
    ).remove_vocals(input_path, output_path)

    assert output_path.read_bytes() == b"fresh instrumental"


def test_mdx_net_wraps_internal_failure_without_leaking_details(
    tmp_path: Path,
) -> None:
    class FailingSeparator(FakeSeparator):
        def separate(
            self,
            input_path: str,
            output_names: dict[str, str],
        ) -> list[str]:
            raise RuntimeError(
                "CUDA failed at C:\\private\\models\\secret.onnx"
            )

    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"input")
    remover = MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=FailingSeparator,
    )

    with pytest.raises(
        AudioExtractionError,
        match="MDX-Net vocal removal failed",
    ) as error:
        remover.remove_vocals(
            input_path,
            tmp_path / "audio_instrumental.wav",
        )

    assert "private" not in str(error.value)


def test_mdx_net_rejects_missing_or_empty_output(
    tmp_path: Path,
) -> None:
    class EmptySeparator(FakeSeparator):
        def separate(
            self,
            input_path: str,
            output_names: dict[str, str],
        ) -> list[str]:
            return []

    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"input")
    remover = MDXNetVocalRemover(
        model_dir=tmp_path / "models",
        separator_factory=EmptySeparator,
    )

    with pytest.raises(
        AudioExtractionError,
        match="empty output",
    ):
        remover.remove_vocals(
            input_path,
            tmp_path / "audio_instrumental.wav",
        )
