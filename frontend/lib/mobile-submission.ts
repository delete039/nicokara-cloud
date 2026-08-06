import type { AudioExtractionOptions } from "@/lib/browser-audio-extractor";
import type { MobileProcessingRoute } from "@/lib/mobile-processing";
import type {
  CreateAudioOnlyJobInput,
  CreateJobInput,
} from "@/services/api";
import type { Job } from "@/types/job";
import type { UploadTicket } from "@/types/upload-ticket";

export type MobileSubmissionStage =
  | "EXTRACTING_AUDIO"
  | "UPLOADING_AUDIO"
  | "FALLBACK_VIDEO"
  | "UPLOADING_VIDEO"
  | "COMPLETED";

export type MobileSubmissionState = {
  stage: MobileSubmissionStage;
  progress: number;
};

export type MobileSubmissionInput = CreateJobInput & {
  route: MobileProcessingRoute;
};

export type MobileSubmissionDependencies = {
  extractAudio(
    video: File,
    options?: AudioExtractionOptions,
  ): Promise<File>;
  uploadAudio(
    input: CreateAudioOnlyJobInput,
    onProgress: (progress: number) => void,
    signal?: AbortSignal,
  ): Promise<Job>;
  uploadVideo(
    input: CreateJobInput,
    onProgress: (progress: number) => void,
    onQueueUpdate?: (ticket: UploadTicket) => void,
  ): Promise<Job>;
};

export type MobileSubmissionOptions = {
  signal?: AbortSignal;
  onQueueUpdate?: (ticket: UploadTicket) => void;
};

function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function videoInput(input: MobileSubmissionInput): CreateJobInput {
  return {
    video: input.video,
    lyricsText: input.lyricsText,
    lyricsFile: input.lyricsFile,
    vocalMode: input.vocalMode,
  };
}

export async function submitMobileJob(
  input: MobileSubmissionInput,
  dependencies: MobileSubmissionDependencies,
  onState: (state: MobileSubmissionState) => void,
  options: MobileSubmissionOptions = {},
): Promise<Job> {
  const emit = (stage: MobileSubmissionStage, progress: number) => {
    onState({ stage, progress });
  };
  const uploadVideo = async () => {
    emit("UPLOADING_VIDEO", 0);
    const job = await dependencies.uploadVideo(
      videoInput(input),
      (progress) => emit("UPLOADING_VIDEO", progress),
      options.onQueueUpdate,
    );
    emit("COMPLETED", 100);
    return job;
  };

  if (input.route !== "AUDIO_ONLY") return uploadVideo();

  emit("EXTRACTING_AUDIO", 0);
  let audio: File;
  try {
    audio = await dependencies.extractAudio(input.video, {
      signal: options.signal,
      onProgress: (progress) => emit("EXTRACTING_AUDIO", progress),
    });
  } catch (reason) {
    if (options.signal?.aborted || isAbortError(reason)) throw reason;
    emit("FALLBACK_VIDEO", 0);
    return uploadVideo();
  }

  emit("UPLOADING_AUDIO", 0);
  const job = await dependencies.uploadAudio(
    {
      audio,
      originalVideoName: input.video.name,
      originalVideoSizeBytes: input.video.size,
      lyricsText: input.lyricsText,
      lyricsFile: input.lyricsFile,
      vocalMode: input.vocalMode,
    },
    (progress) => emit("UPLOADING_AUDIO", progress),
    options.signal,
  );
  emit("COMPLETED", 100);
  return job;
}
