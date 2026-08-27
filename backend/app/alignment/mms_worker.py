from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def recognize_non_silent_ranges(
    audio: Any,
    sample_rate: int,
    *,
    frame_seconds: float,
    top_percent: float,
    threshold_ratio: float,
) -> list[tuple[float, float]]:
    """FA-Kara-compatible RMS activity detection with bounded ranges."""
    import librosa
    import numpy as np

    frame_length = max(2, int(sample_rate * frame_seconds))
    hop_length = max(1, frame_length // 2)
    energy = librosa.feature.rms(
        y=audio,
        frame_length=frame_length,
        hop_length=hop_length,
    )[0]
    if energy.size == 0:
        return []
    threshold = np.percentile(energy, 100 - top_percent) * threshold_ratio
    active_frames = energy > threshold
    times = librosa.frames_to_time(
        np.arange(len(energy)),
        sr=sample_rate,
        hop_length=hop_length,
    )
    duration = len(audio) / sample_rate
    ranges: list[tuple[float, float]] = []
    start: float | None = None
    for time_value, active in zip(times, active_frames, strict=True):
        current = float(time_value)
        if active and start is None:
            start = max(current - frame_seconds / 4, 0.0)
        elif not active and start is not None:
            ranges.append(
                (start, min(current + frame_seconds / 4, duration))
            )
            start = None
    if start is not None:
        ranges.append((start, min(float(times[-1]), duration)))
    return [(start, end) for start, end in ranges if end > start]


def map_packed_time_ms(
    packed_time_ms: int | float,
    non_silent_ranges: list[tuple[float, float]],
) -> int:
    """Map a timestamp in packed non-silent audio back to the source audio."""
    if not non_silent_ranges:
        return round(packed_time_ms)
    adjusted_seconds = float(packed_time_ms) / 1000
    cumulative_duration = 0.0
    for start_seconds, end_seconds in non_silent_ranges:
        segment_duration = end_seconds - start_seconds
        if adjusted_seconds < cumulative_duration + segment_duration:
            return round(
                (start_seconds + adjusted_seconds - cumulative_duration)
                * 1000
            )
        cumulative_duration += segment_duration
    return round(non_silent_ranges[-1][1] * 1000)


def _pack_non_silent_audio(
    audio: Any,
    sample_rate: int,
    ranges: list[tuple[float, float]],
    speed: float,
) -> Any:
    import numpy as np

    segments = []
    total_samples = len(audio)
    for start_seconds, end_seconds in ranges:
        start = max(0, int(start_seconds * sample_rate / speed))
        end = min(
            total_samples,
            int(end_seconds * sample_rate / speed),
        )
        if end > start:
            segments.append(audio[start:end])
    if not segments:
        raise RuntimeError("FA-Kara did not detect usable vocal activity")
    return np.concatenate(segments)


def _adjust_line_boundaries(
    spans: list[dict[str, int | float]],
    line_token_counts: list[int],
    coarse_ranges: list[tuple[float, float]],
    fine_ranges: list[tuple[float, float]],
) -> list[dict[str, int | float]]:
    if sum(line_token_counts) != len(spans):
        raise RuntimeError("FA-Kara line token counts do not match spans")

    line_bounds: list[tuple[int, int]] = []
    offset = 0
    for count in line_token_counts:
        if count > 0:
            line_bounds.append((offset, offset + count - 1))
        offset += count

    for first_index, last_index in line_bounds:
        line_start = int(spans[first_index]["start_ms"])
        line_end = int(spans[last_index]["end_ms"])
        covered = any(
            round(start * 1000) <= line_start
            and math.ceil(end * 1000) >= line_end
            for start, end in coarse_ranges
        )
        if covered:
            continue
        for start, end in coarse_ranges:
            start_ms = round(start * 1000)
            end_ms = math.ceil(end * 1000)
            if start_ms <= line_end <= end_ms:
                first_end = int(spans[first_index]["end_ms"])
                if start_ms < first_end:
                    spans[first_index]["start_ms"] = start_ms
                break

    for line_index, (_, last_index) in enumerate(line_bounds):
        current_end = int(spans[last_index]["end_ms"])
        next_start = (
            int(spans[line_bounds[line_index + 1][0]]["start_ms"])
            if line_index + 1 < len(line_bounds)
            else math.inf
        )
        candidate = next(
            (
                math.ceil(end * 1000)
                for _, end in fine_ranges
                if current_end <= math.ceil(end * 1000) < next_start
            ),
            None,
        )
        if candidate is not None:
            spans[last_index]["end_ms"] = max(
                int(spans[last_index]["start_ms"]),
                candidate,
            )
            continue
        if math.isfinite(next_start) and any(
            round(start * 1000) <= current_end
            and math.ceil(end * 1000) >= next_start
            for start, end in fine_ranges
        ):
            spans[last_index]["end_ms"] = max(
                current_end,
                int(next_start) - 20,
            )
    return spans


def align_audio(
    audio_path: Path,
    tokens: list[str],
    *,
    line_token_counts: list[int],
    device_name: str,
    audio_speed: float,
    silence_window_seconds: float,
    silence_top_percent: float,
    silence_threshold_ratio: float,
    tail_window_seconds: float,
) -> list[dict[str, int | float]]:
    try:
        import librosa
        import torch
        import torchaudio
    except ImportError as exc:
        raise RuntimeError("FA-Kara MMS dependencies are not installed") from exc

    if not audio_path.is_file() or not tokens:
        raise ValueError("FA-Kara requires vocals audio and normalized tokens")
    if audio_speed <= 0:
        raise ValueError("FA-Kara audio speed must be greater than zero")

    device = torch.device(
        "cuda"
        if device_name == "auto" and torch.cuda.is_available()
        else ("cpu" if device_name == "auto" else device_name)
    )
    original_audio, sample_rate = librosa.load(
        str(audio_path),
        sr=None,
        mono=True,
    )
    coarse_ranges = recognize_non_silent_ranges(
        original_audio,
        sample_rate,
        frame_seconds=silence_window_seconds,
        top_percent=silence_top_percent,
        threshold_ratio=silence_threshold_ratio,
    )
    fine_ranges = recognize_non_silent_ranges(
        original_audio,
        sample_rate,
        frame_seconds=tail_window_seconds,
        top_percent=silence_top_percent,
        threshold_ratio=silence_threshold_ratio,
    )
    if not coarse_ranges:
        raise RuntimeError("FA-Kara did not detect vocals in the supplied audio")
    processed_audio = (
        original_audio
        if audio_speed == 1
        else librosa.effects.time_stretch(original_audio, rate=audio_speed)
    )
    packed_audio = _pack_non_silent_audio(
        processed_audio,
        sample_rate,
        coarse_ranges,
        audio_speed,
    )

    bundle = torchaudio.pipelines.MMS_FA
    waveform = torch.from_numpy(packed_audio).float().unsqueeze(0)
    if sample_rate != bundle.sample_rate:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            bundle.sample_rate,
        )

    model = bundle.get_model().to(device)
    try:
        tokenizer = bundle.get_tokenizer()
        aligner = bundle.get_aligner()
        with torch.inference_mode():
            emission, _ = model(waveform.to(device))
            token_spans = aligner(emission[0], tokenizer(tokens))
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if len(token_spans) != len(tokens) or emission.shape[1] <= 0:
        raise RuntimeError("FA-Kara MMS returned incomplete token spans")

    frame_ms = 320 / bundle.sample_rate * 1000 * audio_speed
    results: list[dict[str, int | float]] = []
    for token_group in token_spans:
        if not token_group:
            raise RuntimeError("FA-Kara MMS returned an empty token span")
        frame_count = sum(
            max(1, span.end - span.start) for span in token_group
        )
        score = sum(
            float(span.score) * max(1, span.end - span.start)
            for span in token_group
        ) / frame_count
        results.append(
            {
                "start_ms": map_packed_time_ms(
                    token_group[0].start * frame_ms,
                    coarse_ranges,
                ),
                "end_ms": map_packed_time_ms(
                    token_group[-1].end * frame_ms,
                    coarse_ranges,
                ),
                "score": max(0.0, min(1.0, score)),
            }
        )
    return _adjust_line_boundaries(
        results,
        line_token_counts,
        coarse_ranges,
        fine_ranges,
    )


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
        line_token_counts=[
            int(count) for count in request["line_token_counts"]
        ],
        device_name=args.device,
        audio_speed=float(request["audio_speed"]),
        silence_window_seconds=float(request["silence_window_seconds"]),
        silence_top_percent=float(request["silence_top_percent"]),
        silence_threshold_ratio=float(request["silence_threshold_ratio"]),
        tail_window_seconds=float(request["tail_window_seconds"]),
    )
    output_path.write_text(
        json.dumps({"spans": spans}, ensure_ascii=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
