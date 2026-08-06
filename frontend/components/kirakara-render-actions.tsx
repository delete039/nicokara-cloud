"use client";

import { KirakaraCloudRenderControls } from "@/components/kirakara-cloud-render-controls";
import { KirakaraExportControls } from "@/components/kirakara-export-controls";
import type { KirakaraCapabilities } from "@/lib/kirakara-capabilities";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { Job } from "@/types/job";

export function KirakaraRenderActions({
  capabilities,
  video,
  timeline,
  style,
  jobId,
  vocalMode = "on",
  onCloudRenderQueued,
}: {
  capabilities: KirakaraCapabilities;
  video: File;
  timeline: KirakaraTimeline;
  style: KirakaraStyle;
  jobId: string;
  vocalMode?: string;
  onCloudRenderQueued: (job: Job) => void;
}) {
  if (capabilities.export && capabilities.profile) {
    return (
      <KirakaraExportControls
        video={video}
        timeline={timeline}
        profile={capabilities.profile}
        style={style}
        jobId={jobId}
        vocalMode={vocalMode}
      />
    );
  }

  return (
    <KirakaraCloudRenderControls
      jobId={jobId}
      video={video}
      timeline={timeline}
      style={style}
      emphasized
      onQueued={onCloudRenderQueued}
    />
  );
}
