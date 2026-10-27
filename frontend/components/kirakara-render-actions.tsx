"use client";

import { useState } from "react";

import { KirakaraCloudRenderControls } from "@/components/kirakara-cloud-render-controls";
import { KirakaraExportControls } from "@/components/kirakara-export-controls";
import type { KirakaraCapabilities } from "@/lib/kirakara-capabilities";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { Job } from "@/types/job";
import { downloadVideoUrl } from "@/services/api";

export function KirakaraRenderActions({
  capabilities,
  video,
  timeline,
  style,
  jobId,
  rerender = false,
  disabled = false,
  availableModes = [],
  resultVersion,
  job,
  onCloudRenderQueued,
}: {
  capabilities: KirakaraCapabilities;
  video: File | null;
  timeline: KirakaraTimeline;
  style: KirakaraStyle;
  jobId: string;
  rerender?: boolean;
  disabled?: boolean;
  availableModes?: Array<"on" | "off">;
  resultVersion?: string;
  job?: Job;
  onCloudRenderQueued: (job: Job) => void;
}) {
  const localSupported = Boolean(capabilities.export && capabilities.profile);
  const [activeLocalMode, setActiveLocalMode] = useState<"on" | "off" | null>(null);
  const [localExportState, setLocalExportState] = useState<{
    video: File | null;
    timeline: KirakaraTimeline | null;
    style: KirakaraStyle | null;
    outputs: Partial<Record<"on" | "off", File>>;
  }>({ video: null, timeline: null, style: null, outputs: {} });
  const hasMatchingExportInputs = localExportState.video === video
    && localExportState.timeline === timeline
    && localExportState.style === style;
  const localOutputs = hasMatchingExportInputs ? localExportState.outputs : {};

  return (
    <div className="min-w-0 space-y-3">
      {localSupported && video && (
        <p className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs leading-5 text-muted-foreground">
          两个版本会串联生成：第一个版本完整生成字幕画面，第二个版本仅替换音轨。修改视频、时间轴或字幕样式后会重新开始串联。
        </p>
      )}
      <div className="grid min-w-0 gap-3 xl:grid-cols-2">
      {(["on", "off"] as const).map((mode) => (
        <section key={mode} aria-label={mode === "on" ? "ON VOCAL 导出" : "OFF VOCAL 导出"}
          className="flex min-w-0 flex-col rounded-xl border bg-card p-4">
          <h4 className="font-semibold">{mode === "on" ? "ON VOCAL（原人声）" : "OFF VOCAL（伴奏）"}</h4>
          {video && localSupported && capabilities.profile ? (
            <KirakaraExportControls video={video} timeline={timeline} profile={capabilities.profile}
              style={style} jobId={jobId} vocalMode={mode}
              disabled={disabled || (activeLocalMode !== null && activeLocalMode !== mode)}
              counterpartVideo={localOutputs[mode === "on" ? "off" : "on"] ?? null}
              onExportingChange={(exporting) => {
                setActiveLocalMode((previous) => exporting
                  ? mode
                  : previous === mode ? null : previous);
              }}
              onCompleted={(file) => {
                if (!file) return;
                setLocalExportState((previous) => {
                  const sameInputs = previous.video === video
                    && previous.timeline === timeline
                    && previous.style === style;
                  return {
                    video,
                    timeline,
                    style,
                    outputs: sameInputs
                      ? { ...previous.outputs, [mode]: file }
                      : { [mode]: file },
                  };
                });
              }} />
          ) : <p className="mt-2 text-xs text-muted-foreground">{!video
            ? "重新选择原视频后可发起导出；云端进度和已生成的视频可直接查看。"
            : "当前浏览器不支持本地导出，可使用下方云端导出。"}</p>}
          <KirakaraCloudRenderControls jobId={jobId} video={video} timeline={timeline}
            style={style} vocalMode={mode} disabled={disabled || Boolean(job?.render_pending)} job={job}
            discouraged={localSupported} emphasized={!localSupported}
            audioSwapAvailable={availableModes.includes(mode === "on" ? "off" : "on")}
            rerender={availableModes.includes(mode) || (rerender && availableModes.length === 0)}
            onQueued={onCloudRenderQueued} />
          {availableModes.includes(mode) && (
            <a href={downloadVideoUrl(jobId, resultVersion, mode)}
              className="focus-ring mt-3 inline-flex self-start rounded-lg border px-4 py-2 text-sm font-semibold hover:bg-muted">
              下载已生成的 {mode === "on" ? "ON VOCAL" : "OFF VOCAL"} 云端视频
            </a>
          )}
        </section>
      ))}
      </div>
    </div>
  );
}
