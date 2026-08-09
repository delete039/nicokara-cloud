from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def align_audio(
    audio_path: Path,
    tokens: list[str],
    *,
    device_name: str,
) -> list[dict[str, int | float]]:
    try:
        import torch
        import torchaudio
    except ImportError as exc:
        raise RuntimeError("MMS_FA dependencies are not installed") from exc

    if not audio_path.is_file() or not tokens:
        raise ValueError("MMS_FA requires vocals audio and normalized tokens")

    device = torch.device(
        "cuda"
        if device_name == "auto" and torch.cuda.is_available()
        else ("cpu" if device_name == "auto" else device_name)
    )
    bundle = torchaudio.pipelines.MMS_FA
    waveform, sample_rate = torchaudio.load(str(audio_path))
    waveform = waveform.mean(0, keepdim=True)
    if sample_rate != bundle.sample_rate:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            bundle.sample_rate,
        )

    model = bundle.get_model(with_star=False).to(device)
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()
    with torch.inference_mode():
        emission, _ = model(waveform.to(device))
        token_spans = aligner(emission[0], tokenizer(tokens))

    if len(token_spans) != len(tokens) or emission.shape[1] <= 0:
        raise RuntimeError("MMS_FA returned incomplete token spans")

    frame_ms = (
        waveform.shape[1]
        * 1000
        / bundle.sample_rate
        / emission.shape[1]
    )
    results = []
    for spans in token_spans:
        if not spans:
            raise RuntimeError("MMS_FA returned an empty token span")
        frame_count = sum(max(1, span.end - span.start) for span in spans)
        score = sum(
            float(span.score) * max(1, span.end - span.start)
            for span in spans
        ) / frame_count
        results.append(
            {
                "start_ms": round(spans[0].start * frame_ms),
                "end_ms": round(spans[-1].end * frame_ms),
                "score": max(0.0, min(1.0, score)),
            }
        )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)

    request_path = Path(args.request)
    output_path = Path(args.output)
    request: dict[str, Any] = json.loads(
        request_path.read_text(encoding="utf-8")
    )
    spans = align_audio(
        Path(request["audio_path"]),
        [str(token) for token in request["tokens"]],
        device_name=args.device,
    )
    output_path.write_text(
        json.dumps({"spans": spans}, ensure_ascii=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
