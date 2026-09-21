import { describe, expect, it } from "vitest";

import { sliceAudioWaveform, waveformSeekMs } from "./audio-waveform";

describe("audio waveform slices", () => {
  it("maps a sentence time range to a fixed number of visible bars", () => {
    const bars = sliceAudioWaveform({
      durationMs: 4000,
      samples: [0.1, 0.2, 0.3, 0.4],
    }, 1000, 3000, 4);

    expect(bars).toHaveLength(4);
    expect(bars.every((bar) => bar >= 0.04 && bar <= 1)).toBe(true);
    expect(bars[0]).toBeCloseTo(0.2);
    expect(bars.at(-1)).toBeCloseTo(0.3);
  });

  it("maps waveform clicks and drags to the sentence time range", () => {
    expect(waveformSeekMs(100, 100, 400, 1000, 2000)).toBe(1000);
    expect(waveformSeekMs(300, 100, 400, 1000, 2000)).toBe(1500);
    expect(waveformSeekMs(600, 100, 400, 1000, 2000)).toBe(2000);
  });
});
