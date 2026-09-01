import {
  ALL_FORMATS,
  BlobSource,
  BufferTarget,
  Conversion,
  Input,
  Mp4OutputFormat,
  Output,
  Quality,
  StreamTarget,
  type Target,
  type VideoSample,
} from "mediabunny";

import type { BrowserFileDestination } from "./browser-file-destination";
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
  destination?: BrowserFileDestination;
  onProgress?: (progress: number) => void;
  onValidationStart?: () => void;
  signal?: AbortSignal;
};

export type KirakaraVideoExportResult = {
  fileName: string;
  file: File | null;
  streamed: boolean;
};

type RuntimeTranscodeOptions = Omit<
  KirakaraVideoExportOptions,
  "destination" | "onProgress" | "onValidationStart"
> & {
  target: Target;
  onProgress: (progress: number) => void;
};

export type KirakaraVideoExportRuntime = {
  transcode(options: RuntimeTranscodeOptions): Promise<void>;
};

export type KirakaraVideoOutputValidator = (
  source: File,
  output: File,
) => Promise<void>;

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

async function topLevelMp4BoxTypes(file: File): Promise<string[]> {
  const types: string[] = [];
  let position = 0;
  while (position < file.size) {
    if (file.size - position < 8) {
      throw new Error("导出文件的 MP4 结构不完整");
    }
    const header = new Uint8Array(
      await file.slice(position, Math.min(file.size, position + 16)).arrayBuffer(),
    );
    const view = new DataView(header.buffer, header.byteOffset, header.byteLength);
    let size = view.getUint32(0);
    const type = String.fromCharCode(...header.slice(4, 8));
    let headerSize = 8;
    if (size === 1) {
      if (header.byteLength < 16) {
        throw new Error("导出文件的 MP4 扩展头不完整");
      }
      const high = view.getUint32(8);
      const low = view.getUint32(12);
      size = high * 2 ** 32 + low;
      headerSize = 16;
    } else if (size === 0) {
      size = file.size - position;
    }
    if (
      !Number.isSafeInteger(size) ||
      size < headerSize ||
      position + size > file.size
    ) {
      throw new Error("导出文件包含无效的 MP4 区块");
    }
    types.push(type);
    position += size;
  }
  return types;
}

export async function assertStandardMp4(file: File): Promise<void> {
  const boxTypes = await topLevelMp4BoxTypes(file);
  if (
    !boxTypes.includes("ftyp") ||
    !boxTypes.includes("moov") ||
    !boxTypes.includes("mdat")
  ) {
    throw new Error("导出文件不是完整的标准 MP4");
  }
  if (boxTypes.includes("moof") || boxTypes.includes("mfra")) {
    throw new Error("导出文件仍是分片 MP4，无法保证播放器兼容性");
  }
}

async function primaryVideoDuration(file: File): Promise<number> {
  const input = new Input({
    source: new BlobSource(file),
    formats: ALL_FORMATS,
  });
  try {
    const track = await input.getPrimaryVideoTrack();
    if (!track) throw new Error("视频文件中没有可读取的视频轨道");
    const [firstTimestamp, endTimestamp] = await Promise.all([
      track.getFirstTimestamp(),
      track.computeDuration(),
    ]);
    return Math.max(0, endTimestamp - firstTimestamp);
  } finally {
    input.dispose();
  }
}

export async function validateKirakaraVideoOutput(
  source: File,
  output: File,
  durationProbe: (file: File) => Promise<number> = primaryVideoDuration,
): Promise<void> {
  await assertStandardMp4(output);
  const [sourceDuration, outputDuration] = await Promise.all([
    durationProbe(source),
    durationProbe(output),
  ]);
  if (
    !Number.isFinite(sourceDuration) ||
    !Number.isFinite(outputDuration) ||
    sourceDuration <= 0 ||
    outputDuration <= 0
  ) {
    throw new Error("无法确认导出视频的完整时长");
  }
  const tolerance = Math.max(1, sourceDuration * 0.005);
  if (Math.abs(outputDuration - sourceDuration) > tolerance) {
    throw new Error(
      `导出视频时长校验失败：源视频 ${sourceDuration.toFixed(1)} 秒，` +
      `导出结果 ${outputDuration.toFixed(1)} 秒`,
    );
  }
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
    target,
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
      format: new Mp4OutputFormat({ fastStart: false }),
      target,
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
  validator: KirakaraVideoOutputValidator = validateKirakaraVideoOutput,
): Promise<KirakaraVideoExportResult> {
  ensureNotAborted(options.signal);
  const bufferTarget = options.destination ? null : new BufferTarget();
  const target = options.destination
    ? new StreamTarget(options.destination.writable, {
        chunked: true,
        chunkSize: 8 * 1024 * 1024,
      })
    : bufferTarget;
  if (!target) throw new Error("未找到视频输出目标");

  options.onProgress?.(0);
  await runtime.transcode({
    video: options.video,
    replacementAudio: options.replacementAudio,
    timeline: options.timeline,
    style: options.style,
    profile: options.profile,
    target,
    signal: options.signal,
    onProgress(progress) {
      options.onProgress?.(
        Math.min(99, Math.round(Math.min(1, Math.max(0, progress)) * 100)),
      );
    },
  });
  ensureNotAborted(options.signal);

  const fileName = outputFileName(options.video.name);
  const outputFile = options.destination
    ? await options.destination.getFile()
    : bufferTarget?.buffer
      ? new File([bufferTarget.buffer], fileName, {
          type: "video/mp4",
          lastModified: Date.now(),
        })
      : null;
  if (!outputFile) throw new Error("本地视频导出没有生成可校验的文件");

  options.onValidationStart?.();
  await validator(options.video, outputFile);
  ensureNotAborted(options.signal);
  options.onProgress?.(100);

  return {
    fileName,
    file: options.destination ? null : outputFile,
    streamed: Boolean(options.destination),
  };
}
