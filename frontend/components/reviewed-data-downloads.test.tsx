import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";

async function loadDownloads() {
  const modulePath = "./reviewed-data-downloads";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 4000,
  lines: [
    {
      text: "物語",
      reading: "ものかたり",
      startMs: 2000,
      endMs: 4000,
      units: [
        {
          text: "物語",
          reading: "ものかたり",
          startMs: 2000,
          endMs: 4000,
          moras: [],
        },
      ],
    },
  ],
};

describe("ReviewedDataDownloads", () => {
  it("offers every editable artifact from the current timeline state", async () => {
    const downloads = await loadDownloads();
    expect(downloads, "reviewed data downloads should exist").not.toBeNull();
    if (!downloads) return;

    const html = renderToStaticMarkup(
      <downloads.ReviewedDataDownloads
        jobId="job-1"
        videoName="song.mp4"
        timeline={timeline}
        style={DEFAULT_KIRAKARA_STYLE}
      />,
    );

    expect(html).toContain("下载调整后注音数据");
    expect(html).toContain("下载调整后时间轴");
    expect(html).toContain("下载调整后 ASS 字幕");
    expect(html).toContain("下载 Kirakara 工程 (.krl)");
    expect(html.match(/下载 Kirakara 工程/g)).toHaveLength(1);
  });
});
