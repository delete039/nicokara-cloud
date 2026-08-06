import { describe, expect, it, vi } from "vitest";

async function loadLocalMobileJob() {
  const modulePath = "./local-mobile-job";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("fully local mobile job state machine", () => {
  it("runs every local stage through replaceable adapters", async () => {
    const localMobileJob = await loadLocalMobileJob();
    expect(localMobileJob, "local mobile job module should exist").not.toBeNull();
    if (!localMobileJob) return;

    const states: string[] = [];
    const adapters = {
      prepareModels: vi.fn(async () => undefined),
      extractAudio: vi.fn(async () => new Blob(["audio"])),
      separateVocals: vi.fn(async () => new Blob(["vocals"])),
      alignLyrics: vi.fn(async () => ({ lines: [] })),
      generateSubtitle: vi.fn(async () => "[Script Info]\n"),
      renderVideo: vi.fn(async () => new Blob(["video"], { type: "video/mp4" })),
    };

    const result = await localMobileJob.runLocalMobileJob(
      {
        video: new File(["input"], "song.mp4", { type: "video/mp4" }),
        lyrics: "君の知らない物語",
      },
      adapters,
      (state: { stage: string }) => states.push(state.stage),
    );

    expect(states).toEqual([
      "INSPECTING",
      "PREPARING_MODELS",
      "EXTRACTING_AUDIO",
      "SEPARATING_VOCALS",
      "ALIGNING",
      "GENERATING_SUBTITLE",
      "RENDERING_VIDEO",
      "COMPLETED",
    ]);
    expect(result.video.type).toBe("video/mp4");
    expect(result.subtitle).toContain("Script Info");
  });

  it("ends in FAILED without exposing adapter internals as a successful result", async () => {
    const localMobileJob = await loadLocalMobileJob();
    expect(localMobileJob).not.toBeNull();
    if (!localMobileJob) return;

    const states: Array<{ stage: string; error?: string }> = [];
    const adapters = {
      prepareModels: async () => undefined,
      extractAudio: async () => new Blob(["audio"]),
      separateVocals: async () => new Blob(["vocals"]),
      alignLyrics: async () => {
        throw new Error("ctc adapter failed");
      },
      generateSubtitle: async () => "",
      renderVideo: async () => new Blob(),
    };

    await expect(
      localMobileJob.runLocalMobileJob(
        {
          video: new File(["input"], "song.mp4", { type: "video/mp4" }),
          lyrics: "歌詞",
        },
        adapters,
        (state: { stage: string; error?: string }) => states.push(state),
      ),
    ).rejects.toThrow("ctc adapter failed");

    expect(states.at(-1)).toMatchObject({
      stage: "FAILED",
      error: "ctc adapter failed",
    });
  });
});
