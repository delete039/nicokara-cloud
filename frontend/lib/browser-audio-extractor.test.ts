import { describe, expect, it, vi } from "vitest";

async function loadAudioExtractor() {
  const modulePath = "./browser-audio-extractor";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("browser audio extractor", () => {
  it("returns an M4A file and forwards extraction progress", async () => {
    const extractor = await loadAudioExtractor();
    expect(extractor, "browser audio extractor module should exist").not.toBeNull();
    if (!extractor) return;

    const progress: number[] = [];
    const runtime = {
      extractToM4a: vi.fn(async (
        _video: File,
        onProgress: (value: number) => void,
      ) => {
        onProgress(0.4);
        return new Uint8Array([1, 2, 3]).buffer;
      }),
    };

    const audio = await extractor.extractAudioTrack(
      new File(["video"], "my.song.mp4", { type: "video/mp4" }),
      { onProgress: (value: number) => progress.push(value) },
      runtime,
    );

    expect(audio).toBeInstanceOf(File);
    expect(audio.name).toBe("my.song.audio.m4a");
    expect(audio.type).toBe("audio/mp4");
    expect(audio.size).toBe(3);
    expect(progress).toEqual([0, 40, 100]);
  });

  it("does not start extraction after cancellation", async () => {
    const extractor = await loadAudioExtractor();
    expect(extractor).not.toBeNull();
    if (!extractor) return;

    const controller = new AbortController();
    controller.abort();
    const runtime = {
      extractToM4a: vi.fn(async () => new ArrayBuffer(1)),
    };

    await expect(
      extractor.extractAudioTrack(
        new File(["video"], "song.mp4", { type: "video/mp4" }),
        { signal: controller.signal },
        runtime,
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(runtime.extractToM4a).not.toHaveBeenCalled();
  });

  it("rejects an empty extracted audio file", async () => {
    const extractor = await loadAudioExtractor();
    expect(extractor).not.toBeNull();
    if (!extractor) return;

    await expect(
      extractor.extractAudioTrack(
        new File(["video"], "song.mp4", { type: "video/mp4" }),
        {},
        { extractToM4a: vi.fn(async () => new ArrayBuffer(0)) },
      ),
    ).rejects.toThrow("没有找到可上传的音轨");
  });
});
