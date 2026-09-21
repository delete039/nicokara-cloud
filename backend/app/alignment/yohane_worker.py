from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PRODUCT_BACKEND = Path(__file__).resolve().parents[2]
if str(PRODUCT_BACKEND) not in sys.path:
    sys.path.insert(0, str(PRODUCT_BACKEND))


def align_audio(
    audio_path: Path,
    tokens: list[str],
    *,
    model_dir: Path,
    source_dir: Path,
    device_name: str,
    audio_speed: float,
) -> list[dict[str, int | float]]:
    if not audio_path.is_file() or not tokens:
        raise ValueError("Yohane requires audio and normalized tokens")
    if not model_dir.is_dir():
        raise ValueError(f"Yohane model directory does not exist: {model_dir}")
    if not source_dir.is_dir():
        raise ValueError(f"FA-Kara source directory does not exist: {source_dir}")

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    sys.path.insert(0, str(source_dir.resolve()))
    import torch
    import torchaudio
    from align_yohane import Wav2Vec2ForcedAligner

    if audio_speed <= 0:
        raise ValueError("Yohane audio speed must be greater than zero")
    requested = device_name
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Yohane CUDA device was requested but is unavailable")
    device = torch.device(requested)

    # FA-Kara's Wav2Vec2 aligner performs the channel mixdown itself. Mixing
    # here first turns its second ``mean(0)`` into a scalar on current torch,
    # which makes Transformers fail with ``len() of unsized object``.
    waveform, sample_rate = torchaudio.load(str(audio_path))
    aligner = Wav2Vec2ForcedAligner(str(model_dir))
    aligner.device = device
    aligner.model.to(device)
    token_ids = aligner.tokenize(tokens)
    _, token_spans, target_rate = aligner.align(token_ids, waveform, sample_rate)
    if len(token_spans) != len(tokens):
        raise RuntimeError("Yohane returned incomplete token spans")

    frame_ms = 320 / target_rate * 1000 * audio_speed
    results: list[dict[str, int | float]] = []
    for spans in token_spans:
        if not spans:
            raise RuntimeError("Yohane returned an empty token span")
        scores = [float(span.score) for span in spans]
        results.append(
            {
                "start_ms": round(spans[0].start * frame_ms),
                "end_ms": round(spans[-1].end * frame_ms),
                "score": max(0.0, min(1.0, sum(scores) / len(scores))),
            }
        )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)
    request: dict[str, Any] = json.loads(
        Path(args.request).read_text(encoding="utf-8")
    )
    spans = align_audio(
        Path(request["audio_path"]),
        [str(token) for token in request["tokens"]],
        model_dir=Path(args.model_dir),
        source_dir=Path(args.source_dir),
        device_name=args.device,
        audio_speed=float(request["audio_speed"]),
    )
    Path(args.output).write_text(
        json.dumps({"spans": spans}, ensure_ascii=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
