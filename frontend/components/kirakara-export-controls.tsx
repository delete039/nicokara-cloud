"use client";

import { CircleX, Download, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { createBrowserFileDestination } from "@/lib/browser-file-destination";
import type { KirakaraExportProfile } from "@/lib/kirakara-capabilities";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import { exportKirakaraVideo } from "@/lib/kirakara-video-export";
import { getInstrumentalAudio } from "@/services/api";

type ExportState = "idle" | "exporting" | "completed" | "error";
type ExportPhase = "audio" | "rendering";

export async function resolveExportAudio(
  jobId: string,
  vocalMode: string,
  loader: (
    jobId: string,
    signal?: AbortSignal,
  ) => Promise<File> = getInstrumentalAudio,
  signal?: AbortSignal,
): Promise<File | undefined> {
  return vocalMode === "off" ? loader(jobId, signal) : undefined;
}

export function KirakaraExportControls({
  video,
  timeline,
  profile,
  style,
  jobId = "",
  vocalMode = "on",
}: {
  video: File;
  timeline: KirakaraTimeline;
  profile: KirakaraExportProfile;
  style?: KirakaraStyle;
  jobId?: string;
  vocalMode?: string;
}) {
  const abortController = useRef<AbortController | null>(null);
  const [state, setState] = useState<ExportState>("idle");
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<ExportPhase>("rendering");
  const [outputUrl, setOutputUrl] = useState<string | null>(null);
  const [outputName, setOutputName] = useState<string | null>(null);
  const [streamed, setStreamed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (outputUrl) URL.revokeObjectURL(outputUrl);
    };
  }, [outputUrl]);

  async function startExport() {
    const controller = new AbortController();
    abortController.current = controller;
    setState("exporting");
    setProgress(0);
    setPhase(vocalMode === "off" ? "audio" : "rendering");
    setError(null);
    if (outputUrl) {
      URL.revokeObjectURL(outputUrl);
      setOutputUrl(null);
    }

    const suggestedName = `${video.name.replace(/\.mp4$/i, "") || "nicokara"}.nicokara.mp4`;
    try {
      const destination = await createBrowserFileDestination(suggestedName);
      const replacementAudio = await resolveExportAudio(
        jobId,
        vocalMode,
        getInstrumentalAudio,
        controller.signal,
      );
      setPhase("rendering");
      const result = await exportKirakaraVideo({
        video,
        replacementAudio,
        timeline,
        style,
        profile,
        destination: destination ?? undefined,
        signal: controller.signal,
        onProgress: setProgress,
      });
      setOutputName(result.fileName);
      setStreamed(result.streamed);
      if (result.file) setOutputUrl(URL.createObjectURL(result.file));
      setState("completed");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setState("idle");
        setProgress(0);
      } else {
        setError(reason instanceof Error ? reason.message : "本地视频导出失败");
        setState("error");
      }
    } finally {
      abortController.current = null;
    }
  }

  return (
    <div className="mt-4 border-t pt-4">
      <div className="flex flex-wrap items-center gap-3">
        {state !== "exporting" && (
          <button
            type="button"
            onClick={startExport}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
          >
            <Download className="size-4" />
            {state === "error" ? "重新导出" : "导出本地视频"}
          </button>
        )}
        {state === "exporting" && (
          <button
            type="button"
            onClick={() => abortController.current?.abort()}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border border-destructive/40 px-4 py-2.5 text-sm font-semibold text-destructive"
          >
            <CircleX className="size-4" />
            取消导出
          </button>
        )}
        {state === "completed" && outputUrl && outputName && (
          <a
            href={outputUrl}
            download={outputName}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-semibold"
          >
            <Download className="size-4" />
            下载生成视频
          </a>
        )}
        {state === "completed" && streamed && (
          <span className="text-sm font-medium text-primary">视频已保存</span>
        )}
      </div>

      {state === "exporting" && (
        <div className="mt-4" aria-live="polite">
          <div className="mb-2 flex items-center justify-between gap-4 text-sm">
            <span className="flex items-center gap-2">
              <LoaderCircle className="size-4 animate-spin" />
              {phase === "audio" ? "正在下载云端伴奏" : "正在本地渲染视频"}
            </span>
            <span className="font-medium">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        {vocalMode === "off"
          ? "OFF VOCAL 会使用云端 UVR 伴奏；原视频仍保留在当前设备中。"
          : "视频保留在当前设备中处理，不会重新上传到服务器。"}
      </p>
    </div>
  );
}
