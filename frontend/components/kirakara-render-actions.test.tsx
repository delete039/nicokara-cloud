import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import { KirakaraRenderActions } from "./kirakara-render-actions";
import type { Job } from "@/types/job";

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 0,
  lines: [],
};
const video = new File(["video"], "song.mp4", { type: "video/mp4" });
const profile = {
  codec: "avc1.42E01E",
  width: 1280,
  height: 720,
  framerate: 30,
  bitrate: 4_000_000,
};

describe("KirakaraRenderActions", () => {
  const renderingJob: Job = {
    id: "job-1", status: "PROCESSING", stage: "RENDERING_VIDEO", progress: 90,
    original_video_name: "song.mp4", video_size_bytes: 5, video_sha256: "test",
    lyrics_source: "text", input_mode: "AUDIO_ONLY", has_timeline: true,
    render_pending: true, render_vocal_mode: "off", available_vocal_modes: ["on"],
    error_code: null, error_message: null, created_at: "2026-09-16", updated_at: "2026-09-16",
  };

  function renderJob(job: Job, localVideo: File | null = video) {
    return renderToStaticMarkup(<KirakaraRenderActions
      capabilities={{ preview: true, export: false, profile: null }} video={localVideo}
      timeline={timeline} style={DEFAULT_KIRAKARA_STYLE} jobId="job-1" job={job}
      availableModes={job.available_vocal_modes} onCloudRenderQueued={vi.fn()} />);
  }

  it("keeps cloud render progress inside the matching vocal export card", () => {
    const html = renderJob(renderingJob);
    const [onCard, offCard] = html.split('aria-label="OFF VOCAL 导出"');
    expect(onCard).not.toContain('role="progressbar"');
    expect(offCard).toContain('aria-label="OFF VOCAL 云端导出进度"');
    expect(offCard).toContain('aria-valuenow="90"');
    expect(offCard).toContain("正在合成最终视频");
    expect(onCard).toContain("下载已生成的 ON VOCAL 云端视频");
  });

  it("shows the queue position and existing downloads without reselecting local video", () => {
    const html = renderJob({ ...renderingJob, status: "UPLOADED", stage: "CLOUD_RENDER_QUEUED",
      progress: 10, queue_position: 2, queue_size: 3 }, null);
    expect(html).toContain("排队第 2 位");
    expect(html).toContain("下载已生成的 ON VOCAL 云端视频");
    expect(html).not.toContain("导出本地视频");
  });

  it("replaces processing progress with completion and shows both downloads once", () => {
    const html = renderJob({ ...renderingJob, status: "COMPLETED", stage: "VIDEO_RENDERING_COMPLETE",
      progress: 100, render_pending: false, available_vocal_modes: ["on", "off"] }, null);
    expect(html).toContain("云端视频已生成");
    expect(html.match(/下载已生成的 ON VOCAL 云端视频/g)).toHaveLength(1);
    expect(html.match(/下载已生成的 OFF VOCAL 云端视频/g)).toHaveLength(1);
    expect(html).not.toContain("正在合成最终视频");
  });

  it("shows an interrupted render beside its button rather than indefinite progress", () => {
    const html = renderJob({ ...renderingJob, status: "FAILED", render_pending: false,
      error_code: "VIDEO_RENDERING_FAILED", error_message: "Rendering failed" });
    expect(html).toContain("云端导出失败");
    expect(html).not.toContain('aria-busy="true"');
  });
  it("offers cloud export as a discouraged alternative when browser export is supported", () => {
    const html = renderToStaticMarkup(
      <KirakaraRenderActions
        capabilities={{ preview: true, export: true, profile }}
        video={video}
        timeline={timeline}
        style={DEFAULT_KIRAKARA_STYLE}
        jobId="job-1"
        onCloudRenderQueued={vi.fn()}
      />,
    );

    expect(html).toContain("导出本地视频");
    expect(html).toContain("云端导出（不推荐）");
    expect(html).toContain("会重新上传原视频并占用服务器渲染队列");
    expect(html).toContain("ON VOCAL（原人声）");
    expect(html).toContain("OFF VOCAL（伴奏）");
    expect(html.match(/导出本地视频/g)).toHaveLength(2);
    expect(html.match(/云端导出（不推荐）/g)).toHaveLength(2);
  });

  it("shows only cloud rendering when browser export is unsupported", () => {
    const html = renderToStaticMarkup(
      <KirakaraRenderActions
        capabilities={{ preview: true, export: false, profile: null }}
        video={video}
        timeline={timeline}
        style={DEFAULT_KIRAKARA_STYLE}
        jobId="job-1"
        onCloudRenderQueued={vi.fn()}
      />,
    );

    expect(html).toContain("进入云端渲染队列");
    expect(html).not.toContain("导出本地视频");
    expect(html).not.toContain("不推荐");
    expect(html.match(/进入云端渲染队列/g)).toHaveLength(2);
  });
});
