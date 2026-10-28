from contextlib import nullcontext
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.alignment.ctc import emission_windows, infer_emissions, align_moras


@pytest.mark.parametrize("samples", [400, 401, 719, 720, 320000, 4755072])
def test_windows_cover_exact_frame_grid_once(samples):
    actual = []
    for start, end, first, last in emission_windows(samples):
        assert start % 320 == 0
        assert end <= samples
        assert end - start <= 1200 * 320 + 80
        assert last <= (end - start - 400) // 320 + 1
        actual.extend(start // 320 + frame for frame in range(first, last))
    assert actual == list(range((samples - 400) // 320 + 1))


def test_inference_keeps_context_but_discards_duplicate_frames(monkeypatch):
    class Tensor(np.ndarray):
        def detach(self): return self
        def cpu(self): return self
        def clone(self): return self.copy()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        inference_mode=nullcontext, cat=lambda xs, dim: np.concatenate(xs, axis=dim)
    ))
    waveform = np.arange(16000 * 65).reshape(1, -1)
    lengths = []

    def model(chunk):
        lengths.append(chunk.shape[-1])
        count = (chunk.shape[-1] - 400) // 320 + 1
        return chunk[:, :count * 320:320, None].view(Tensor)

    result = infer_emissions(waveform, model)
    assert max(lengths) < 16000 * 25
    assert len(lengths) == 4
    np.testing.assert_array_equal(result[0, :, 0], np.arange(result.shape[1]) * 320)


def test_inference_rejects_short_audio():
    with pytest.raises(ValueError, match="too short"):
        emission_windows(399)


def test_ctc_keeps_instrumental_gap_between_moras_not_inside_one():
    # A weak spurious /s/ precedes an instrumental; the actual /sho/ follows.
    values = np.full((800, 5), -12., dtype=np.float32)
    values[:, 0] = -0.01
    values[1, 1] = -0.01
    values[10, 2] = -0.01
    values[700, 2] = -0.2
    values[701, 3] = -0.01
    values[702, 4] = -0.01
    baseline = align_moras(values, [[1], [2, 3, 4]], blank=0, internal_blank_penalty=0)
    assert baseline[1][0].start == 10
    result = align_moras(values, [[1], [2, 3, 4]], blank=0)
    assert result[0][0].start == 1
    assert [span.start for span in result[1]] == [700, 701, 702]
    assert result[1][0].score == pytest.approx(np.exp(-0.2))


def test_ctc_repeated_tokens_require_blank_and_keep_sustained_vowel():
    values = np.full((110, 2), -20., dtype=np.float32)
    values[:, 0] = 0
    values[1:101, 1] = 0
    values[1:101, 0] = -20
    values[102, 1] = 0
    values[102, 0] = -20
    groups = align_moras(values, [[1], [1]], blank=0)
    assert [(s.start, s.end) for group in groups for s in group] == [(1, 101), (102, 103)]


@pytest.mark.parametrize("tokens", [[[0]], [[9]], [[]], []])
def test_ctc_rejects_invalid_tokens(tokens):
    with pytest.raises(ValueError):
        align_moras(np.zeros((5, 2)), tokens, blank=0)
