import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import { KirakaraReviewEditor } from "./kirakara-review-editor";

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 2000,
  lines: [
    {
      text: "今日",
      reading: "きょう",
      startMs: 1000,
      endMs: 2000,
      units: [
        { text: "今日", reading: "きょう", startMs: 1000, endMs: 2000, moras: [] },
      ],
    },
  ],
};

describe("KirakaraReviewEditor", () => {
  it("shows a visual timeline, timing controls, and ruby review fields", () => {
    const html = renderToStaticMarkup(
      <KirakaraReviewEditor timeline={timeline} onChange={vi.fn()} onSeek={vi.fn()} />,
    );

    expect(html).toContain("时间轴与注音检查");
    expect(html).toContain("整体偏移");
    expect(html).toContain("开始时间");
    expect(html).toContain("结束时间");
    expect(html).toContain("今日");
    expect(html).toContain("きょう");
  });
});
