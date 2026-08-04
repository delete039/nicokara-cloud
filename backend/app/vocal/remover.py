from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal as scisignal

from app.video.audio import AudioExtractionError


class VocalRemover:
    """Remove center-panned vocals from stereo audio via STFT masking.

    For each time-frequency bin the left/right magnitudes are compared;
    bins where the channels are nearly equal are treated as centre-panned
    content (typically vocals) and attenuated.  The remaining signal keeps
    the side-panned instruments largely intact.
    """

    def __init__(
        self,
        *,
        fft_size: int = 2048,
        hop_size: int = 512,
        centre_mask_threshold: float = 0.5,
        centre_reduction_db: float = -30.0,
    ) -> None:
        self.fft_size = fft_size
        self.hop_size = hop_size
        self.centre_mask_threshold = centre_mask_threshold
        self.centre_reduction_db = centre_reduction_db

    def remove_vocals(self, input_path: Path, output_path: Path) -> None:
        try:
            import av
        except ImportError:
            raise AudioExtractionError(
                "av package is required for vocal removal"
            )

        input_container = av.open(str(input_path))
        input_stream = input_container.streams.audio[0]

        samples: list[np.ndarray] = []
        for frame in input_container.decode(audio=0):
            array = frame.to_ndarray()
            channel_count = len(frame.layout.channels)
            if frame.format.is_planar:
                stereo = array[:2]
            else:
                packed = array.reshape(-1)
                stereo = packed.reshape(-1, channel_count).T[:2]
            if stereo.shape[0] == 1:
                stereo = np.repeat(stereo, 2, axis=0)
            samples.append(stereo)

        input_container.close()

        if not samples:
            raise AudioExtractionError("No audio data found for vocal removal")

        audio = np.concatenate(samples, axis=1)
        sample_rate = float(input_stream.sample_rate)

        reduction_linear = 10.0 ** (self.centre_reduction_db / 20.0)

        left = audio[0, :].astype(np.float64)
        right = audio[1, :].astype(np.float64)

        _, _, left_stft = scisignal.stft(
            left, fs=sample_rate, nperseg=self.fft_size, noverlap=self.fft_size - self.hop_size
        )
        _, _, right_stft = scisignal.stft(
            right, fs=sample_rate, nperseg=self.fft_size, noverlap=self.fft_size - self.hop_size
        )

        left_mag = np.abs(left_stft)
        right_mag = np.abs(right_stft)

        sum_mag = left_mag + right_mag
        sum_mag = np.maximum(sum_mag, 1e-12)
        diff_ratio = np.abs(left_mag - right_mag) / sum_mag

        mask = np.where(
            diff_ratio < self.centre_mask_threshold,
            reduction_linear,
            1.0,
        )

        left_stft_filtered = left_stft * mask
        right_stft_filtered = right_stft * mask

        _, left_filtered = scisignal.istft(
            left_stft_filtered, fs=sample_rate, nperseg=self.fft_size, noverlap=self.fft_size - self.hop_size
        )
        _, right_filtered = scisignal.istft(
            right_stft_filtered, fs=sample_rate, nperseg=self.fft_size, noverlap=self.fft_size - self.hop_size
        )

        min_len = min(len(left_filtered), len(right_filtered))
        left_filtered = left_filtered[:min_len]
        right_filtered = right_filtered[:min_len]

        output_stereo = np.stack([left_filtered, right_filtered], axis=0)
        output_stereo = np.clip(output_stereo, -32768, 32767).astype(np.int16)
        output_packed = output_stereo.T.reshape(1, -1)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_container = av.open(str(output_path), mode="w")
        output_stream = output_container.add_stream(
            "pcm_s16le",
            rate=input_stream.sample_rate,
            layout="stereo",
        )
        output_frame = av.AudioFrame.from_ndarray(
            output_packed, layout="stereo", format="s16"
        )
        output_frame.sample_rate = input_stream.sample_rate
        for packet in output_stream.encode(output_frame):
            output_container.mux(packet)
        for packet in output_stream.encode(None):
            output_container.mux(packet)
        output_container.close()

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AudioExtractionError(
                "Vocal removal produced an empty output file"
            )
