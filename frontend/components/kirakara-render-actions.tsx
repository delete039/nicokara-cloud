"use client";

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
  return (
    <div className="grid min-w-0 gap-3 xl:grid-cols-2">
      {(["on", "off"] as const).map((mode) => (
        <section key={mode} aria-label={mode === "on" ? "ON VOCAL 导出" : "OFF VOCAL 导出"}
          className="flex min-w-0 flex-col rounded-xl border bg-card p-4">
          <h4 className="font-semibold">{mode === "on" ? "ON VOCAL（原人声）" : "OFF VOCAL（伴奏）"}</h4>
          {video && localSupported && capabilities.profile ? (
            <KirakaraExportControls video={video} timeline={timeline} profile={capabilities.profile}
              style={style} jobId={jobId} vocalMode={mode} disabled={disabled} />
          ) : <p className="mt-2 text-xs text-muted-foreground">{!video
            ? "重新选择原视频后可发起导出；云端进度和已生成的视频可直接查看。"
            : "当前浏览器不支持本地导出，可使用下方云端导出。"}</p>}
          <KirakaraCloudRenderControls jobId={jobId} video={video} timeline={timeline}
            style={style} vocalMode={mode} disabled={disabled || Boolean(job?.render_pending)} job={job}
            discouraged={localSupported} emphasized={!localSupported}
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
  );
}
