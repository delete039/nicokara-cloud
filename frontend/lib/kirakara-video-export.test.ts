import { describe, expect, it, vi } from "vitest";
import {
  ALL_FORMATS,
  BlobSource,
  BufferTarget,
  Input,
  Mp4OutputFormat,
  Output,
  StreamTarget,
} from "mediabunny";

import {
  assertStandardMp4,
  composableConversionOptions,
  exportKirakaraVideo,
  paintKirakaraVideoFrame,
  validateKirakaraVideoOutput,
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

function mp4Box(type: string): Uint8Array {
  const box = new Uint8Array(8);
  new DataView(box.buffer).setUint32(0, box.byteLength);
  [...type].forEach((character, index) => {
    box[4 + index] = character.charCodeAt(0);
  });
  return box;
}

function mp4File(
  types: string[],
  name = "output.mp4",
): File {
  return new File(types.map(mp4Box), name, { type: "video/mp4" });
}

function bufferedRuntime(output = mp4File(["ftyp", "mdat", "moov"])): KirakaraVideoExportRuntime {
  return {
    transcode: vi.fn(async ({ target, onProgress }) => {
      expect(target).toBeInstanceOf(BufferTarget);
      onProgress(0.501);
      (target as BufferTarget).buffer = await output.arrayBuffer();
    }),
  };
}

describe("standard MP4 validation", () => {
  it("accepts a regular MP4 and rejects fragmented MP4 boxes", async () => {
    await expect(
      assertStandardMp4(mp4File(["ftyp", "mdat", "moov"])),
    ).resolves.toBeUndefined();

    await expect(
      assertStandardMp4(
        mp4File(["ftyp", "moov", "moof", "mdat", "mfra"]),
      ),
    ).rejects.toThrow("分片 MP4");
  });

  it("rejects an output whose duration differs from the source", async () => {
    const source = new File(["source"], "source.mp4");
    const output = mp4File(["ftyp", "mdat", "moov"]);
    const durationProbe = vi.fn(async (file: File) =>
      file === source ? 264 : 2
    );

    await expect(
      validateKirakaraVideoOutput(source, output, durationProbe),
    ).rejects.toThrow("源视频 264.0 秒，导出结果 2.0 秒");
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
  it("never attaches metadata tags to a composable conversion", () => {
    const input = new Input({
      source: new BlobSource(new File(["video"], "song.mp4")),
      formats: ALL_FORMATS,
    });
    const output = new Output({
      format: new Mp4OutputFormat(),
      target: new BufferTarget(),
    });

    const options = composableConversionOptions({
      input,
      output,
      tracks: "primary",
      video: { discard: true },
    });

    expect(options.composable).toBe(true);
    expect(options).not.toHaveProperty("tags");
  });

  it("returns a named MP4 and forwards bounded progress", async () => {
    const runtime = bufferedRuntime();
    const progress = vi.fn();
    const validator = vi.fn().mockResolvedValue(undefined);

    const result = await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4", { type: "video/mp4" }),
        timeline,
        profile,
        onProgress: progress,
      },
      runtime,
      validator,
    );

    expect(result.streamed).toBe(false);
    expect(result.file).toMatchObject({
      name: "song.nicokara.mp4",
      type: "video/mp4",
    });
    expect(result.file?.size).toBe(24);
    expect(progress).toHaveBeenCalledWith(50);
    expect(progress).toHaveBeenLastCalledWith(100);
    expect(validator).toHaveBeenCalledWith(
      expect.objectContaining({ name: "song.mp4" }),
      expect.objectContaining({ name: "song.nicokara.mp4" }),
    );
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
    const runtime = bufferedRuntime();

    await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4"),
        timeline,
        profile,
        replacementAudio,
      },
      runtime,
      vi.fn().mockResolvedValue(undefined),
    );

    expect(runtime.transcode).toHaveBeenCalledWith(
      expect.objectContaining({ replacementAudio }),
    );
  });

  it("forwards the preview style to the export renderer", async () => {
    const style = { ...DEFAULT_KIRAKARA_STYLE, fontSize: 72 };
    const runtime = bufferedRuntime();

    await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4"),
        timeline,
        profile,
        style,
      },
      runtime,
      vi.fn().mockResolvedValue(undefined),
    );

    expect(runtime.transcode).toHaveBeenCalledWith(
      expect.objectContaining({ style }),
    );
  });

  it("validates a streamed file before reporting it as saved", async () => {
    const savedFile = mp4File(["ftyp", "mdat", "moov"], "saved.mp4");
    const destination = {
      writable: new WritableStream(),
      getFile: vi.fn().mockResolvedValue(savedFile),
    };
    const runtime: KirakaraVideoExportRuntime = {
      transcode: vi.fn(async ({ target }) => {
        expect(target).toBeInstanceOf(StreamTarget);
      }),
    };
    const validator = vi.fn().mockResolvedValue(undefined);
    const validationStarted = vi.fn();

    const result = await exportKirakaraVideo(
      {
        video: new File(["video"], "song.mp4"),
        timeline,
        profile,
        destination,
        onValidationStart: validationStarted,
      },
      runtime,
      validator,
    );

    expect(destination.getFile).toHaveBeenCalledOnce();
    expect(validationStarted).toHaveBeenCalledOnce();
    expect(validator).toHaveBeenCalledWith(
      expect.objectContaining({ name: "song.mp4" }),
      savedFile,
    );
    expect(result).toMatchObject({ file: null, streamed: true });
  });

  it("does not report completion when output validation fails", async () => {
    const progress = vi.fn();

    await expect(
      exportKirakaraVideo(
        {
          video: new File(["video"], "song.mp4"),
          timeline,
          profile,
          onProgress: progress,
        },
        bufferedRuntime(),
        vi.fn().mockRejectedValue(new Error("导出视频时长校验失败")),
      ),
    ).rejects.toThrow("导出视频时长校验失败");
    expect(progress).not.toHaveBeenCalledWith(100);
  });
});
