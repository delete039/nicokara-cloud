import {
  ALL_FORMATS,
  AppendOnlyStreamTarget,
  BlobSource,
  Conversion,
  Input,
  Mp4OutputFormat,
  Output,
  Quality,
  type VideoSample,
} from "mediabunny";

import type { KirakaraExportProfile } from "./kirakara-capabilities";
import {
  drawKirakaraFrame,
  type KirakaraCanvasContext,
} from "./kirakara-canvas";
import type { KirakaraStyle } from "./kirakara-style";
import {
  activeKirakaraFrame,
  type KirakaraTimeline,
} from "./kirakara-timeline";

export type KirakaraVideoExportOptions = {
  video: File;
  replacementAudio?: File;
  timeline: KirakaraTimeline;
  style?: KirakaraStyle;
  profile: KirakaraExportProfile;
  destination?: WritableStream<Uint8Array>;
  onProgress?: (progress: number) => void;
  signal?: AbortSignal;
};

export type KirakaraVideoExportResult = {
  fileName: string;
  file: File | null;
  streamed: boolean;
};

type RuntimeTranscodeOptions = Omit<
  KirakaraVideoExportOptions,
  "destination" | "onProgress"
> & {
  writable: WritableStream<Uint8Array>;
  onProgress: (progress: number) => void;
};

export type KirakaraVideoExportRuntime = {
  transcode(options: RuntimeTranscodeOptions): Promise<void>;
};

type DrawableVideoSample = Pick<VideoSample, "timestamp" | "drawWithFit">;
type ConversionInitOptions = Parameters<typeof Conversion.init>[0];
type ConversionOptionsWithoutOwnership = Omit<
  ConversionInitOptions,
  "composable" | "tags"
>;
type ComposableConversionInitOptions = ConversionOptionsWithoutOwnership & {
  composable: true;
  tags?: never;
};

export function composableConversionOptions(
  options: ConversionOptionsWithoutOwnership,
): ComposableConversionInitOptions {
  const {
    composable: ignoredComposable,
    tags: ignoredTags,
    ...safeOptions
  } = options as ConversionInitOptions;
  void ignoredComposable;
  void ignoredTags;
  return { ...safeOptions, composable: true };
}

function abortError(): DOMException {
  return new DOMException("本地视频导出已取消", "AbortError");
}

function ensureNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function outputFileName(videoName: string): string {
  const baseName = videoName.replace(/\.mp4$/i, "") || "nicokara";
  return `${baseName}.nicokara.mp4`;
}

export function createChunkedBlobWriter(type: string): {
  writable: WritableStream<Uint8Array>;
  toBlob: () => Blob;
} {
  const chunks: Uint8Array[] = [];
  return {
    writable: new WritableStream<Uint8Array>({
      write(chunk) {
        chunks.push(chunk.slice());
      },
    }),
    toBlob: () => new Blob(chunks, { type }),
  };
}

export function paintKirakaraVideoFrame(
  sample: DrawableVideoSample,
  context: KirakaraCanvasContext,
  timeline: KirakaraTimeline,
  style?: KirakaraStyle,
): void {
  const { width, height } = context.canvas;
  context.clearRect(0, 0, width, height);
  sample.drawWithFit(
    context as CanvasRenderingContext2D,
    { fit: "contain" },
  );
  drawKirakaraFrame(
    context,
    activeKirakaraFrame(timeline, sample.timestamp * 1000),
    { clear: false, style },
  );
}

const mediabunnyRuntime: KirakaraVideoExportRuntime = {
  async transcode({
    video,
    replacementAudio,
    timeline,
    style,
    profile,
    writable,
    onProgress,
    signal,
  }) {
    ensureNotAborted(signal);
    const canvas = document.createElement("canvas");
    canvas.width = profile.width;
    canvas.height = profile.height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("当前浏览器无法创建视频渲染画布");

    const videoInput = new Input({
      source: new BlobSource(video),
      formats: ALL_FORMATS,
    });
    const output = new Output({
      format: new Mp4OutputFormat({
        fastStart: "fragmented",
        minimumFragmentDuration: 1,
      }),
      target: new AppendOnlyStreamTarget(writable),
    });
    const videoOptions: ConversionOptionsWithoutOwnership = {
      input: videoInput,
      output,
      tracks: "primary",
      video: {
        width: profile.width,
        height: profile.height,
        fit: "contain",
        frameRate: profile.framerate,
        codec: "avc",
        quality: new Quality({ bitrate: profile.bitrate }),
        keyFrameInterval: 2,
        forceTranscode: true,
        processedWidth: profile.width,
        processedHeight: profile.height,
        process(sample) {
          ensureNotAborted(signal);
          paintKirakaraVideoFrame(sample, context, timeline, style);
          return canvas;
        },
      },
      audio: replacementAudio ? { discard: true } : {},
      showWarnings: false,
    };
    const videoConversion = await Conversion.init(
      replacementAudio
        ? composableConversionOptions(videoOptions)
        : { ...videoOptions, tags: {} },
    );

    const replacementInput = replacementAudio
      ? new Input({
          source: new BlobSource(replacementAudio),
          formats: ALL_FORMATS,
        })
      : null;
    const audioConversion = replacementInput
      ? await Conversion.init(composableConversionOptions({
          input: replacementInput,
          output,
          tracks: "primary",
          video: { discard: true },
          audio: {},
          showWarnings: false,
        }))
      : null;

    if (
      !videoConversion.isValid ||
      !videoConversion.utilizedTracks.some((track) => track.type === "video")
    ) {
      const reasons = videoConversion.discardedTracks
        .map((item) => item.reason)
        .join(", ");
      throw new Error(
        reasons
          ? `当前浏览器无法导出此视频：${reasons}`
          : "当前浏览器无法解码或编码此视频",
      );
    }
    if (
      audioConversion &&
      !audioConversion.utilizedTracks.some((track) => track.type === "audio")
    ) {
      throw new Error("当前浏览器无法编码云端伴奏音轨");
    }

    videoConversion.onProgress = (progress) => onProgress(progress);
    const cancel = () => {
      void videoConversion.cancel();
      if (audioConversion) void audioConversion.cancel();
    };
    signal?.addEventListener("abort", cancel, { once: true });
    try {
      ensureNotAborted(signal);
      if (audioConversion) {
        await output.start();
        await Promise.all([
          videoConversion.execute(),
          audioConversion.execute(),
        ]);
        await output.finalize();
      } else {
        await videoConversion.execute();
      }
      ensureNotAborted(signal);
    } catch (reason) {
      if (output.state !== "finalized" && output.state !== "canceled") {
        await output.cancel().catch(() => undefined);
      }
      if (signal?.aborted) throw abortError();
      throw reason;
    } finally {
      signal?.removeEventListener("abort", cancel);
      videoInput.dispose();
      replacementInput?.dispose();
    }
  },
};

export async function exportKirakaraVideo(
  options: KirakaraVideoExportOptions,
  runtime: KirakaraVideoExportRuntime = mediabunnyRuntime,
): Promise<KirakaraVideoExportResult> {
  ensureNotAborted(options.signal);
  const collector = options.destination
    ? null
    : createChunkedBlobWriter("video/mp4");
  const writable = options.destination ?? collector?.writable;
  if (!writable) throw new Error("未找到视频输出目标");

  options.onProgress?.(0);
  await runtime.transcode({
    video: options.video,
    replacementAudio: options.replacementAudio,
    timeline: options.timeline,
    style: options.style,
    profile: options.profile,
    writable,
    signal: options.signal,
    onProgress(progress) {
      options.onProgress?.(
        Math.round(Math.min(1, Math.max(0, progress)) * 100),
      );
    },
  });
  ensureNotAborted(options.signal);
  options.onProgress?.(100);

  const fileName = outputFileName(options.video.name);
  return {
    fileName,
    file: collector
      ? new File([collector.toBlob()], fileName, {
          type: "video/mp4",
          lastModified: Date.now(),
        })
      : null,
    streamed: Boolean(options.destination),
  };
}
