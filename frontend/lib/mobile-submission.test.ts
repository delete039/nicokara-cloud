import { describe, expect, it, vi } from "vitest";

import type { Job } from "@/types/job";

async function loadMobileSubmission() {
  const modulePath = "./mobile-submission";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

const video = new File(["video"], "song.mp4", { type: "video/mp4" });
const audio = new File(["audio"], "song.audio.m4a", { type: "audio/mp4" });
const job = { id: "job-1", input_mode: "AUDIO_ONLY" } as Job;

function createDependencies() {
  return {
    extractAudio: vi.fn(async (
      _video: File,
      options: { onProgress?: (progress: number) => void },
    ) => {
      options.onProgress?.(40);
      return audio;
    }),
    uploadAudio: vi.fn(async (
      _input: unknown,
      onProgress: (progress: number) => void,
    ) => {
      onProgress(50);
      return job;
    }),
    uploadVideo: vi.fn(async () => job),
  };
}

const input = {
  video,
  lyricsText: "lyrics",
  vocalMode: "on",
};

describe("mobile submission orchestration", () => {
  it("extracts and uploads audio without sending the video", async () => {
    const submission = await loadMobileSubmission();
    expect(submission, "mobile submission module should exist").not.toBeNull();
    if (!submission) return;

    const dependencies = createDependencies();
    const states: Array<{ stage: string; progress: number }> = [];

    await expect(
      submission.submitMobileJob(
        { ...input, route: "AUDIO_ONLY" },
        dependencies,
        (state: { stage: string; progress: number }) => states.push(state),
      ),
    ).resolves.toBe(job);

    expect(dependencies.uploadAudio).toHaveBeenCalledWith(
      expect.objectContaining({
        audio,
        originalVideoName: "song.mp4",
        originalVideoSizeBytes: video.size,
      }),
      expect.any(Function),
      undefined,
    );
    expect(dependencies.uploadVideo).not.toHaveBeenCalled();
    expect(states).toEqual([
      { stage: "EXTRACTING_AUDIO", progress: 0 },
      { stage: "EXTRACTING_AUDIO", progress: 40 },
      { stage: "UPLOADING_AUDIO", progress: 0 },
      { stage: "UPLOADING_AUDIO", progress: 50 },
      { stage: "COMPLETED", progress: 100 },
    ]);
  });

  it("falls back to video upload when local extraction is unsupported", async () => {
    const submission = await loadMobileSubmission();
    expect(submission).not.toBeNull();
    if (!submission) return;

    const dependencies = createDependencies();
    dependencies.extractAudio.mockRejectedValueOnce(
      new Error("unsupported audio codec"),
    );
    const states: Array<{ stage: string; progress: number }> = [];

    await submission.submitMobileJob(
      { ...input, route: "AUDIO_ONLY" },
      dependencies,
      (state: { stage: string; progress: number }) => states.push(state),
    );

    expect(dependencies.uploadAudio).not.toHaveBeenCalled();
    expect(dependencies.uploadVideo).toHaveBeenCalledOnce();
    expect(states).toContainEqual({ stage: "FALLBACK_VIDEO", progress: 0 });
  });

  it("does not fall back to video after the user cancels extraction", async () => {
    const submission = await loadMobileSubmission();
    expect(submission).not.toBeNull();
    if (!submission) return;

    const dependencies = createDependencies();
    dependencies.extractAudio.mockRejectedValueOnce(
      new DOMException("canceled", "AbortError"),
    );

    await expect(
      submission.submitMobileJob(
        { ...input, route: "AUDIO_ONLY" },
        dependencies,
        vi.fn(),
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(dependencies.uploadVideo).not.toHaveBeenCalled();
  });

  it("does not upload the video after an audio upload failure", async () => {
    const submission = await loadMobileSubmission();
    expect(submission).not.toBeNull();
    if (!submission) return;

    const dependencies = createDependencies();
    dependencies.uploadAudio.mockRejectedValueOnce(new Error("server failed"));

    await expect(
      submission.submitMobileJob(
        { ...input, route: "AUDIO_ONLY" },
        dependencies,
        vi.fn(),
      ),
    ).rejects.toThrow("server failed");
    expect(dependencies.uploadVideo).not.toHaveBeenCalled();
  });
});
