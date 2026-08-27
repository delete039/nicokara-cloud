import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { ErrorFeedback } from "@/lib/error-feedback";
import { ApiRequestError } from "@/services/api";
import {
  cloudRenderErrorFeedback,
  KirakaraCloudRenderControls,
} from "./kirakara-cloud-render-controls";

describe("KirakaraCloudRenderControls", () => {
  it("offers the render queue when local export is unsupported", () => {
    const timeline: KirakaraTimeline = {
      confidence: 1,
      warnings: [],
      durationMs: 0,
      lines: [],
    };
    const html = renderToStaticMarkup(
      <KirakaraCloudRenderControls
        jobId="job-1"
        video={new File(["video"], "song.mp4", { type: "video/mp4" })}
        timeline={timeline}
        emphasized
        onQueued={vi.fn()}
      />,
    );

    expect(html).toContain("进入云端渲染队列");
    expect(html).toContain("不会重新识别");
  });

  it("labels a completed cloud result as a rerender", () => {
    const timeline: KirakaraTimeline = {
      confidence: 1,
      warnings: [],
      durationMs: 0,
      lines: [],
    };
    const html = renderToStaticMarkup(
      <KirakaraCloudRenderControls
        jobId="job-1"
        video={new File(["video"], "song.mp4", { type: "video/mp4" })}
        timeline={timeline}
        rerender
        onQueued={vi.fn()}
      />,
    );

    expect(html).toContain("按当前设置重新云端渲染");
  });

  it("keeps actionable validation guidance for the full error panel", () => {
    const feedback: ErrorFeedback = {
      title: "提交内容未通过校验",
      description: "调整后的时间轴未提供。",
      solutions: ["点击“返回修改”并检查时间轴。"],
      technicalDetails: ["HTTP 状态码：422"],
      retryable: false,
    };

    expect(cloudRenderErrorFeedback(new ApiRequestError(feedback))).toBe(
      feedback,
    );
  });
});
