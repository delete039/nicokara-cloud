export type AudioWaveform = {
  samples: number[];
  durationMs: number;
};

export function waveformSeekMs(
  clientX: number,
  trackLeft: number,
  trackWidth: number,
  startMs: number,
  endMs: number,
): number {
  if (!Number.isFinite(clientX) || !Number.isFinite(trackLeft) || trackWidth <= 0) return Math.round(startMs);
  const progress = Math.min(1, Math.max(0, (clientX - trackLeft) / trackWidth));
  return Math.round(startMs + (endMs - startMs) * progress);
}

export function sliceAudioWaveform(
  waveform: AudioWaveform,
  startMs: number,
  endMs: number,
  barCount = 120,
): number[] {
  const count = Math.max(1, Math.floor(barCount));
  const durationMs = Math.max(1, waveform.durationMs);
  const start = Math.max(0, Math.min(durationMs, startMs));
  const end = Math.max(start, Math.min(durationMs, endMs));
  const firstSample = Math.floor(start / durationMs * waveform.samples.length);
  const lastSample = Math.max(firstSample + 1, Math.ceil(end / durationMs * waveform.samples.length));
  const result: number[] = [];
  for (let index = 0; index < count; index += 1) {
    const from = firstSample + Math.floor((lastSample - firstSample) * index / count);
    const to = Math.max(from + 1, firstSample + Math.ceil((lastSample - firstSample) * (index + 1) / count));
    let peak = 0;
    for (let sampleIndex = from; sampleIndex < Math.min(to, waveform.samples.length); sampleIndex += 1) {
      peak = Math.max(peak, waveform.samples[sampleIndex] ?? 0);
    }
    result.push(Math.min(1, Math.max(0.04, peak)));
  }
  return result;
}

export async function decodeAudioWaveform(
  source: Blob,
  sampleCount = 2400,
): Promise<AudioWaveform> {
  const runtime = globalThis as typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };
  const Context = runtime.AudioContext ?? runtime.webkitAudioContext;
  if (!Context) throw new Error("当前浏览器不支持音频波形");

  const context = new Context();
  try {
    const buffer = await context.decodeAudioData(await source.arrayBuffer());
    const length = Math.max(1, Math.floor(sampleCount));
    const samples = Array.from({ length }, (_, index) => {
      const from = Math.floor(index / length * buffer.length);
      const to = Math.max(from + 1, Math.floor((index + 1) / length * buffer.length));
      let peak = 0;
      for (let frame = from; frame < Math.min(to, buffer.length); frame += 1) {
        for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
          peak = Math.max(peak, Math.abs(buffer.getChannelData(channel)[frame] ?? 0));
        }
      }
      return Math.min(1, Math.max(0.04, peak));
    });
    return { samples, durationMs: buffer.duration * 1000 };
  } finally {
    await context.close().catch(() => undefined);
  }
}
