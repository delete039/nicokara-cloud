import {
  ALL_FORMATS,
  BlobSource,
  BufferTarget,
  Conversion,
  Input,
  Mp4OutputFormat,
  Output,
} from "mediabunny";

export type AudioExtractionOptions = {
  onProgress?: (progress: number) => void;
  signal?: AbortSignal;
};

export type BrowserAudioExtractionRuntime = {
  extractToM4a(
    video: File,
    onProgress: (progress: number) => void,
    signal?: AbortSignal,
  ): Promise<ArrayBuffer>;
};

function abortError(): DOMException {
  return new DOMException("音频提取已取消", "AbortError");
}

function ensureNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function audioFileName(videoName: string): string {
  const baseName = videoName.replace(/\.mp4$/i, "") || "nicokara";
  return `${baseName}.audio.m4a`;
}

const mediabunnyRuntime: BrowserAudioExtractionRuntime = {
  async extractToM4a(video, onProgress, signal) {
    ensureNotAborted(signal);
    const target = new BufferTarget();
    const input = new Input({
      source: new BlobSource(video),
      formats: ALL_FORMATS,
    });
    const output = new Output({
      format: new Mp4OutputFormat(),
      target,
    });
    const conversion = await Conversion.init({
      input,
      output,
      tracks: "primary",
      video: { discard: true },
      tags: {},
    });

    if (
      !conversion.isValid ||
      !conversion.utilizedTracks.some((track) => track.type === "audio")
    ) {
      throw new Error("视频中没有可直接提取的兼容音轨");
    }

    conversion.onProgress = (progress) => onProgress(progress);
    const cancel = () => {
      void conversion.cancel();
    };
    signal?.addEventListener("abort", cancel, { once: true });
    try {
      ensureNotAborted(signal);
      await conversion.execute();
      ensureNotAborted(signal);
      if (!target.buffer) throw new Error("音频提取没有生成输出文件");
      return target.buffer;
    } catch (reason) {
      if (signal?.aborted) throw abortError();
      throw reason;
    } finally {
      signal?.removeEventListener("abort", cancel);
    }
  },
};

export async function extractAudioTrack(
  video: File,
  options: AudioExtractionOptions = {},
  runtime: BrowserAudioExtractionRuntime = mediabunnyRuntime,
): Promise<File> {
  ensureNotAborted(options.signal);
  options.onProgress?.(0);
  const buffer = await runtime.extractToM4a(
    video,
    (progress) => {
      const percentage = Math.round(Math.min(1, Math.max(0, progress)) * 100);
      options.onProgress?.(percentage);
    },
    options.signal,
  );
  ensureNotAborted(options.signal);
  if (buffer.byteLength === 0) {
    throw new Error("视频中没有找到可上传的音轨");
  }
  options.onProgress?.(100);
  return new File([buffer], audioFileName(video.name), {
    type: "audio/mp4",
    lastModified: video.lastModified,
  });
}
