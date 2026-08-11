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
        {
          text: "今日",
          reading: "きょう",
          startMs: 1000,
          endMs: 2000,
          moras: [
            { reading: "きょ", startMs: 1000, endMs: 1600, matched: true },
            { reading: "う", startMs: 1600, endMs: 2000, matched: true },
          ],
        },
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
    expect(html).toContain('data-current-line-selector="true"');
    expect(html).toContain('data-timing-panel="true"');
    expect(html).toContain('data-ruby-panel="true"');
    expect(html.match(/lg:h-\[32rem\]/g)).toHaveLength(2);
    expect(html).toContain('data-ruby-scroll="true"');
    expect(html).toContain("lg:overflow-y-auto");
    expect(html).toContain("lg:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)]");
    expect(html).toContain("设置时间轴");
    expect(html).toContain("设置注音");
    expect(html.match(/data-mora-segment=/g)).toHaveLength(2);
    expect(html).toContain('data-mora-boundary="0"');
    expect(html).toContain("きょ");
    expect(html).toContain("う");
    expect(html).not.toContain('data-timeline-line-draggable="true"');
    expect(html).not.toContain("拖动第 1 句");
    expect(html).toContain('data-line-edge="start"');
    expect(html).toContain('data-line-edge="end"');
    expect(html).toContain("cursor-ew-resize");
    expect(html).toContain("touch-none");
    expect(html).toContain("开始时间");
    expect(html).toContain("结束时间");
    expect(html).toContain("今日");
    expect(html).toContain("きょう");
  });

  it("separates crowded mora boundary handles into visual lanes", () => {
    const denseTimeline: KirakaraTimeline = {
      ...timeline,
      lines: [{
        ...timeline.lines[0],
        text: "あいうえお",
        reading: "あいうえお",
        units: [{
          text: "あいうえお",
          reading: "あいうえお",
          startMs: 1000,
          endMs: 2000,
          moras: [
            { reading: "あ", startMs: 1000, endMs: 1200, matched: true },
            { reading: "い", startMs: 1200, endMs: 1210, matched: true },
            { reading: "う", startMs: 1210, endMs: 1220, matched: true },
            { reading: "え", startMs: 1220, endMs: 1230, matched: true },
            { reading: "お", startMs: 1230, endMs: 2000, matched: true },
          ],
        }],
      }],
    };

    const html = renderToStaticMarkup(
      <KirakaraReviewEditor
        timeline={denseTimeline}
        onChange={vi.fn()}
        onSeek={vi.fn()}
      />,
    );

    expect(html).toContain('data-mora-handle-lane="0"');
    expect(html).toContain('data-mora-handle-lane="1"');
    expect(html).toContain('data-mora-handle-lane="2"');
    expect(html).toContain('data-mora-handle-lane="3"');
  });
});
