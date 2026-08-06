import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import { KirakaraRenderActions } from "./kirakara-render-actions";

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
  it("shows only local export when browser export is supported", () => {
    const html = renderToStaticMarkup(
      <KirakaraRenderActions
        capabilities={{ supported: true, export: true, profile, reasons: [] }}
        video={video}
        timeline={timeline}
        style={DEFAULT_KIRAKARA_STYLE}
        jobId="job-1"
        onCloudRenderQueued={vi.fn()}
      />,
    );

    expect(html).toContain("导出本地视频");
    expect(html).not.toContain("进入云端渲染队列");
  });

  it("shows only cloud rendering when browser export is unsupported", () => {
    const html = renderToStaticMarkup(
      <KirakaraRenderActions
        capabilities={{ supported: true, export: false, profile: null, reasons: [] }}
        video={video}
        timeline={timeline}
        style={DEFAULT_KIRAKARA_STYLE}
        jobId="job-1"
        onCloudRenderQueued={vi.fn()}
      />,
    );

    expect(html).toContain("进入云端渲染队列");
    expect(html).not.toContain("导出本地视频");
  });
});
