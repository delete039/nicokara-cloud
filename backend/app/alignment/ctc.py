"""Bounded wav2vec2 inference on a single, continuous CTC frame grid."""
from __future__ import annotations

from typing import Any, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CharacterSpan:
    token: int
    start: int
    end: int
    score: float


def align_moras(
    emission: Any, tokens: list[list[int]], *, blank: int,
    internal_blank_penalty: float = 0.1,
) -> list[list[CharacterSpan]]:
    """CTC Viterbi with a duration prior on silence *inside* a mora.

    Ordinary CTC treats every character boundary identically and can strand
    a consonant before an instrumental break, then finish its vowel afterward.
    Blank frames between complete moras remain free; within a mora they pay
    0.1 log probability per 20 ms. Acoustic scores remain unmodified, and the
    caller's duration/confidence validation still applies to the output.
    """
    import numpy as np

    values = np.asarray(emission, dtype=np.float32)
    flat = [int(token) for group in tokens for token in group]
    if (values.ndim != 2 or not len(values) or not flat or
            any(not group for group in tokens) or not np.isfinite(values).all()):
        raise ValueError("CTC requires finite emissions and nonempty mora tokens")
    if (not 0 <= blank < values.shape[1] or blank in flat or
            min(flat) < 0 or max(flat) >= values.shape[1] or
            not np.isfinite(internal_blank_penalty) or internal_blank_penalty < 0):
        raise ValueError("Invalid CTC token or blank configuration")
    count = len(flat)
    if len(values) < count + sum(a == b for a, b in zip(flat, flat[1:])):
        raise ValueError("Audio has too few CTC frames for the supplied lyrics")
    labels = np.full(2 * count + 1, blank, dtype=np.int64)
    if len(values) * len(labels) > 100_000_000:
        raise ValueError("CTC audio/lyric combination exceeds the alignment memory budget")
    labels[1::2] = flat
    penalty = np.zeros(len(labels), dtype=np.float32)
    penalty[2:-1:2] = internal_blank_penalty
    boundary = 0
    for group in tokens:
        boundary += len(group)
        penalty[2 * boundary] = 0
    can_skip = np.zeros(len(labels), dtype=bool)
    can_skip[3::2] = np.asarray(flat[1:]) != np.asarray(flat[:-1])
    previous = np.full(len(labels), -np.inf, dtype=np.float32)
    previous[0] = values[0, blank]
    previous[1] = values[0, flat[0]]
    back = np.zeros((len(values), len(labels)), dtype=np.uint8)
    for frame in range(1, len(values)):
        best = previous.copy()
        advance = previous[:-1] > best[1:]
        best[1:] = np.maximum(best[1:], previous[:-1])
        back[frame, 1:] = advance
        skip = can_skip[2:] & (previous[:-2] > best[2:])
        best[2:] = np.where(skip, previous[:-2], best[2:])
        back[frame, 2:] = np.where(skip, 2, back[frame, 2:])
        previous = best + values[frame, labels] - penalty
    state = len(labels) - (1 if previous[-1] >= previous[-2] else 2)
    if not np.isfinite(previous[state]):
        raise RuntimeError("No complete CTC path for the supplied lyrics")
    path = np.empty(len(values), dtype=np.int64)
    for frame in range(len(values) - 1, -1, -1):
        path[frame] = state
        state -= int(back[frame, state])
    spans = []
    for index, token in enumerate(flat):
        frames = np.flatnonzero(path == 2 * index + 1)
        if not len(frames):
            raise RuntimeError("CTC returned an incomplete character path")
        spans.append(CharacterSpan(token, int(frames[0]), int(frames[-1]) + 1,
                                   float(np.exp(values[frames, token]).mean())))
    groups = []
    offset = 0
    for group in tokens:
        groups.append(spans[offset:offset + len(group)])
        offset += len(group)
    return groups


def emission_windows(
    sample_count: int,
    *,
    stride: int = 320,
    receptive_field: int = 400,
    core_frames: int = 1000,
    context_frames: int = 100,
) -> list[tuple[int, int, int, int]]:
    """Return sample slices and local frame slices, without duplicates or drift.

    Wav2vec2 emits floor((samples - 400) / 320) + 1 frames. Slicing
    on this grid matters: concatenating arbitrary 20-second emissions loses
    a frame at every boundary and gradually moves the end of a song.
    """
    if min(stride, receptive_field, core_frames) <= 0 or context_frames < 0:
        raise ValueError("Invalid acoustic inference window configuration")
    total = (sample_count - receptive_field) // stride + 1
    if total <= 0:
        raise ValueError("Audio is too short for wav2vec2 inference")
    windows = []
    for first in range(0, total, core_frames):
        last = min(total, first + core_frames)
        left = max(0, first - context_frames)
        right = min(total, last + context_frames)
        windows.append((left * stride, (right - 1) * stride + receptive_field,
                        first - left, last - left))
    return windows


def infer_emissions(waveform: Any, infer: Callable[[Any], Any]) -> Any:
    """Infer 20-second cores with 2 seconds of context on either side.

    Retain only the small CPU emission matrix; model activations and attention
    never grow with song length. Forced alignment still uses the whole song.
    """
    import torch

    pieces = []
    with torch.inference_mode():
        for start, end, first, last in emission_windows(waveform.shape[-1]):
            emission = infer(waveform[..., start:end])
            if emission.ndim != 3 or emission.shape[1] < last:
                raise RuntimeError("Acoustic model returned an incompatible frame grid")
            pieces.append(emission[:, first:last].detach().cpu().clone())
            del emission
    return torch.cat(pieces, dim=1)
