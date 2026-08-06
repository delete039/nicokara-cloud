export type LocalMobileJobStage =
  | "INSPECTING"
  | "PREPARING_MODELS"
  | "EXTRACTING_AUDIO"
  | "SEPARATING_VOCALS"
  | "ALIGNING"
  | "GENERATING_SUBTITLE"
  | "RENDERING_VIDEO"
  | "COMPLETED"
  | "FAILED"
  | "CANCELED";

export type LocalMobileJobState = {
  stage: LocalMobileJobStage;
  progress: number;
  error?: string;
};

export type LocalMobileJobInput = {
  video: File;
  lyrics: string;
};

export type LocalMobileJobResult = {
  video: Blob;
  subtitle: string;
};

export type LocalMobileJobAdapters<TTimeline = unknown> = {
  prepareModels(signal?: AbortSignal): Promise<void>;
  extractAudio(video: File, signal?: AbortSignal): Promise<Blob>;
  separateVocals(audio: Blob, signal?: AbortSignal): Promise<Blob>;
  alignLyrics(
    vocals: Blob,
    lyrics: string,
    signal?: AbortSignal,
  ): Promise<TTimeline>;
  generateSubtitle(
    timeline: TTimeline,
    signal?: AbortSignal,
  ): Promise<string>;
  renderVideo(
    video: File,
    subtitle: string,
    signal?: AbortSignal,
  ): Promise<Blob>;
};

const STAGE_PROGRESS: Record<LocalMobileJobStage, number> = {
  INSPECTING: 2,
  PREPARING_MODELS: 8,
  EXTRACTING_AUDIO: 18,
  SEPARATING_VOCALS: 45,
  ALIGNING: 70,
  GENERATING_SUBTITLE: 85,
  RENDERING_VIDEO: 92,
  COMPLETED: 100,
  FAILED: 0,
  CANCELED: 0,
};

function abortError(): DOMException {
  return new DOMException("Local processing was canceled", "AbortError");
}

function ensureNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

export async function runLocalMobileJob<TTimeline>(
  input: LocalMobileJobInput,
  adapters: LocalMobileJobAdapters<TTimeline>,
  onState: (state: LocalMobileJobState) => void,
  signal?: AbortSignal,
): Promise<LocalMobileJobResult> {
  const emit = (stage: LocalMobileJobStage, error?: string) => {
    onState({ stage, progress: STAGE_PROGRESS[stage], error });
  };

  try {
    emit("INSPECTING");
    ensureNotAborted(signal);
    if (!input.video.name.toLowerCase().endsWith(".mp4")) {
      throw new Error("Local processing requires an MP4 video");
    }
    if (!input.lyrics.trim()) {
      throw new Error("Local processing requires lyrics");
    }

    emit("PREPARING_MODELS");
    await adapters.prepareModels(signal);
    ensureNotAborted(signal);

    emit("EXTRACTING_AUDIO");
    const audio = await adapters.extractAudio(input.video, signal);
    ensureNotAborted(signal);

    emit("SEPARATING_VOCALS");
    const vocals = await adapters.separateVocals(audio, signal);
    ensureNotAborted(signal);

    emit("ALIGNING");
    const timeline = await adapters.alignLyrics(
      vocals,
      input.lyrics.trim(),
      signal,
    );
    ensureNotAborted(signal);

    emit("GENERATING_SUBTITLE");
    const subtitle = await adapters.generateSubtitle(timeline, signal);
    ensureNotAborted(signal);

    emit("RENDERING_VIDEO");
    const video = await adapters.renderVideo(input.video, subtitle, signal);
    ensureNotAborted(signal);

    emit("COMPLETED");
    return { video, subtitle };
  } catch (reason) {
    if (signal?.aborted || (reason instanceof DOMException && reason.name === "AbortError")) {
      emit("CANCELED");
    } else {
      emit("FAILED", reason instanceof Error ? reason.message : "Local processing failed");
    }
    throw reason;
  }
}
