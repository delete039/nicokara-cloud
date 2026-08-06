import { describe, expect, it, vi } from "vitest";

import {
  createChunkedBlobWriter,
  exportKirakaraVideo,
  paintKirakaraVideoFrame,
  type KirakaraVideoExportRuntime,
} from "./kirakara-video-export";
import type { KirakaraTimeline } from "./kirakara-timeline";
import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 2000,
  lines: [
    {
      text: "君",
      reading: "きみ",
      startMs: 0,
      endMs: 2000,
      units: [
        {
          text: "君",
          reading: "きみ",
          startMs: 0,
          endMs: 2000,
          moras: [],
        },
      ],
    },
  ],
};

const profile = {
  codec: "avc1.42E01E",
  width: 1280,
  height: 720,
  framerate: 30,
  bitrate: 4_000_000,
};

describe("createChunkedBlobWriter", () => {
  it("collects sequential muxer chunks without joining them eagerly", async () => {
    const writer = createChunkedBlobWriter("video/mp4");
    const streamWriter = writer.writable.getWriter();
    await streamWriter.write(new Uint8Array([1, 2]));
    await streamWriter.write(new Uint8Array([3]));
    await streamWriter.close();

    expect(new Uint8Array(await writer.toBlob().arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3]),
    );
  });
});

describe("paintKirakaraVideoFrame", () => {
  it("draws the decoded video before the karaoke overlay", () => {
    const calls: string[] = [];
    const sample = {
      timestamp: 1,
      drawWithFit: vi.fn(() => calls.push("video")),
    };
    const context = {
      canvas: { width: 1280, height: 720 },
      clearRect: vi.fn(),
      fillRect: vi.fn(),
      fillText: vi.fn(() => calls.push("overlay")),
      strokeText: vi.fn(),
      measureText: vi.fn((text: string) => ({ width: text.length * 40 })),
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      rect: vi.fn(),
      clip: vi.fn(),
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 0,
      font: "",
      textBaseline: "alphabetic" as CanvasTextBaseline,
    };

    paintKirakaraVideoFrame(sample, context, timeline);

    expect(sample.drawWithFit).toHaveBeenCalledWith(context, { fit: "contain" });
    expect(calls.slice(0, 2)).toEqual(["video", "overlay"]);
  });
});

describe("exportKirakaraVideo", () => {
  it("returns a named MP4 and forwards bounded progress", async () => {
    const runtime: KirakaraVideoExportRuntime = {
      transcode: vi.fn(async ({ writable, onProgress }) => {
        const writer = writable.getWriter();
        onProgress(0.501);
        await writer.write(new Uint8Array([0, 1, 2]));
        await writer.close();
      }),
    };
    const progress = vi.fn();

    const result = await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4", { type: "video/mp4" }),
        timeline,
        profile,
        onProgress: progress,
      },
      runtime,
    );

    expect(result.streamed).toBe(false);
    expect(result.file).toMatchObject({
      name: "song.nicokara.mp4",
      type: "video/mp4",
    });
    expect(result.file?.size).toBe(3);
    expect(progress).toHaveBeenCalledWith(50);
  });

  it("does not start transcoding when already canceled", async () => {
    const controller = new AbortController();
    controller.abort();
    const runtime: KirakaraVideoExportRuntime = {
      transcode: vi.fn(),
    };

    await expect(
      exportKirakaraVideo(
        {
          video: new File(["video"], "song.mp4"),
          timeline,
          profile,
          signal: controller.signal,
        },
        runtime,
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(runtime.transcode).not.toHaveBeenCalled();
  });

  it("forwards a cloud instrumental as the replacement output audio", async () => {
    const replacementAudio = new File(["instrumental"], "instrumental.wav", {
      type: "audio/wav",
    });
    const runtime: KirakaraVideoExportRuntime = {
      transcode: vi.fn(async ({ writable }) => {
        await writable.getWriter().close();
      }),
    };

    await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4"),
        timeline,
        profile,
        replacementAudio,
      },
      runtime,
    );

    expect(runtime.transcode).toHaveBeenCalledWith(
      expect.objectContaining({ replacementAudio }),
    );
  });

  it("forwards the preview style to the export renderer", async () => {
    const style = { ...DEFAULT_KIRAKARA_STYLE, fontSize: 72 };
    const runtime: KirakaraVideoExportRuntime = {
      transcode: vi.fn(async ({ writable }) => {
        await writable.getWriter().close();
      }),
    };

    await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4"),
        timeline,
        profile,
        style,
      },
      runtime,
    );

    expect(runtime.transcode).toHaveBeenCalledWith(
      expect.objectContaining({ style }),
    );
  });
});
