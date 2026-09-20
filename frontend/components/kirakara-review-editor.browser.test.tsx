/* @vitest-environment jsdom */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import { KirakaraReviewEditor, timingDragSeekMs } from "./kirakara-review-editor";

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 5000,
  lines: [
    {
      text: "今日",
      reading: "きょう",
      startMs: 1000,
      endMs: 2000,
      units: [{
        text: "今日",
        reading: "きょう",
        startMs: 1000,
        endMs: 2000,
        moras: [
          { reading: "きょ", startMs: 1000, endMs: 1600, matched: true },
          { reading: "う", startMs: 1600, endMs: 2000, matched: true },
        ],
      }],
    },
    {
      text: "明日",
      reading: "あした",
      startMs: 3000,
      endMs: 4000,
      units: [{
        text: "明日",
        reading: "あした",
        startMs: 3000,
        endMs: 4000,
        moras: [],
      }],
    },
  ],
};

type EditorOverrides = Partial<Parameters<typeof KirakaraReviewEditor>[0]>;

function renderEditor(overrides: EditorOverrides = {}) {
  const props: Parameters<typeof KirakaraReviewEditor>[0] = {
    timeline,
    editingLineIndex: 0,
    previewLeadMs: 100,
    onEditingLineChange: vi.fn(),
    onChange: vi.fn(),
    onSeek: vi.fn(),
    ...overrides,
  };
  return { ...render(<KirakaraReviewEditor {...props} />), props };
}

describe("KirakaraReviewEditor browser behavior", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({ matches: false })),
    });
  });

  afterEach(() => cleanup());

  it("REQ-SELECT-03 routes the next button through the controlled selection callback", () => {
    const onEditingLineChange = vi.fn();
    renderEditor({ onEditingLineChange });
    fireEvent.click(screen.getByRole("button", { name: "下一句" }));
    expect(onEditingLineChange).toHaveBeenCalledWith(1);
  });

  it("REQ-PLACEMENT-03 keeps undo and line navigation inside the timing panel", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: "撤销" }).closest('[data-timing-panel="true"]')).toBeTruthy();
    expect(screen.getByRole("button", { name: "下一句" }).closest('[data-timing-panel="true"]')).toBeTruthy();
  });

  it("REQ-HELP-01 shows the timeline guide after a 500ms hover delay", () => {
    vi.useFakeTimers();
    try {
      renderEditor();
      const trigger = screen.getByRole("button", { name: "查看时间轴使用说明" });
      fireEvent.mouseEnter(trigger);

      act(() => vi.advanceTimersByTime(499));
      expect(screen.queryByRole("tooltip")).toBeNull();
      act(() => vi.advanceTimersByTime(1));

      const guide = screen.getByRole("tooltip");
      expect(guide.className).toContain("bg-muted");
      expect(guide.textContent).toContain("定位歌词");
      expect(guide.textContent).toContain("复听提前量");
      expect(guide.textContent).toContain("Z、X、C");
      expect(guide.textContent).toContain("U、I、O、P");
      fireEvent.mouseLeave(trigger);
      expect(screen.queryByRole("tooltip")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("REQ-KEY-05 marks all timestamp controls for playback shortcuts", () => {
    const { container } = renderEditor();
    const timestampControls = container.querySelectorAll('[data-time-boundary-kind], input[type="number"]');
    expect([...timestampControls].every((element) => element.getAttribute("data-playback-shortcuts") === "true")).toBe(true);
  });

  it("REQ-TIME-01 exposes line-start, Mora, and line-end boundary controls", () => {
    const { container } = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    expect(container.querySelector('[data-time-boundary-kind="line-start"]')).toBeTruthy();
    expect(container.querySelector('[data-time-boundary-kind="mora"]')).toBeTruthy();
    expect(container.querySelector('[data-time-boundary-kind="mora-start"]')).toBeTruthy();
    expect(container.querySelector('[data-time-boundary-kind="line-end"]')).toBeTruthy();
  });

  it("REQ-TIME-02 shows the focused boundary absolute time to milliseconds", () => {
    renderEditor();
    fireEvent.focus(screen.getByRole("button", { name: "调整当前歌词行的开始时间" }));
    expect(screen.getByText("1.000").getAttribute("data-time-boundary-tooltip")).toBe("true");
  });

  it("REQ-TIME-03 refreshes the selected boundary tooltip after a timeline update", () => {
    const { rerender, props } = renderEditor();
    fireEvent.focus(screen.getByRole("button", { name: "调整当前歌词行的开始时间" }));
    const updated = { ...timeline, lines: [{ ...timeline.lines[0], startMs: 1100 }, timeline.lines[1]] };
    rerender(<KirakaraReviewEditor {...props} timeline={updated} />);
    expect(screen.getByText("1.100")).toBeTruthy();
  });

  it("REQ-TIME-04 hides the boundary tooltip on blur", () => {
    renderEditor();
    const handle = screen.getByRole("button", { name: "调整当前歌词行的开始时间" });
    fireEvent.focus(handle);
    fireEvent.blur(handle);
    expect(screen.queryByText("1.000")).toBeNull();
  });

  it("REQ-TIME-05 keeps the tooltip above and outside pointer hit testing", () => {
    renderEditor();
    fireEvent.focus(screen.getByRole("button", { name: "调整当前歌词行的开始时间" }));
    expect(screen.getByText("1.000").className).toContain("pointer-events-none");
    expect(screen.getByText("1.000").className).toContain("bottom-full");
  });

  it("REQ-TIME-06 represents all boundary controls with one selection attribute", () => {
    const { container } = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    expect([...container.querySelectorAll("[data-time-boundary-kind]")].map((element) =>
      element.getAttribute("data-time-boundary-kind"))).toEqual([
      "line-start",
      "line-end",
      "mora",
      "mora-start",
    ]);
  });

  it("REQ-LEAD-04 calculates drag completion seek from the adjusted boundary", () => {
    expect(timingDragSeekMs(timeline, 0, { kind: "mora-boundary", boundaryIndex: 0 }, 100)).toBe(1500);
  });

  it("REQ-LEAD-05 seeks with preview lead after a keyboard boundary adjustment", () => {
    const onSeek = vi.fn();
    renderEditor({ onSeek });
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "调整第 1 个 Mora 分界" }), { key: "ArrowRight" });
    expect(onSeek).toHaveBeenCalledWith(1510);
  });

  it("REQ-MORA-SELECT-01 reveals only the selected outer Mora boundary", () => {
    const { container } = renderEditor();
    expect(container.querySelector('[data-mora-outer-edge="start"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    expect(container.querySelector('[data-mora-outer-edge="start"]')).toBeTruthy();
    expect(container.querySelector('[data-mora-outer-edge="end"]')).toBeNull();
  });

  it("REQ-INPUT-01 does not submit an incomplete line time while typing", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    fireEvent.change(screen.getByLabelText("开始时间（秒）"), { target: { value: "1.2" } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("REQ-INPUT-02 submits the complete line time on blur", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    const input = screen.getByLabelText("开始时间（秒）");
    fireEvent.change(input, { target: { value: "1.2" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({ startMs: 1200, endMs: 2000 })]),
    }));
  });

  it("REQ-INPUT-03 submits a selected Mora time only after blur", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    const input = screen.getByLabelText("Mora 开始（秒）");
    fireEvent.change(input, { target: { value: "1.1" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({ startMs: 1100, endMs: 2000 })]),
    }));
  });

  it("REQ-INPUT-04 clamps an overflowing line end and refreshes the draft", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    const input = screen.getByLabelText("结束时间（秒）");
    fireEvent.change(input, { target: { value: "4.000" } });
    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({ endMs: 3000 })]),
    }));
    expect((input as HTMLInputElement).value).toBe("3.000");
  });

  it("REQ-LEAD-11 uses preview lead after a precise Mora edit", () => {
    const onSeek = vi.fn();
    renderEditor({ onSeek });
    fireEvent.click(screen.getByRole("button", { name: "う" }));
    const input = screen.getByLabelText("Mora 开始（秒）");
    fireEvent.change(input, { target: { value: "1.700" } });
    fireEvent.blur(input);
    expect(onSeek).toHaveBeenCalledWith(1600);
  });

  it("REQ-MORA-SHORTCUT-01 selects the next Mora with the default right bracket", () => {
    renderEditor();
    fireEvent.keyDown(window, { key: "]" });
    expect(screen.getByText("当前 Mora：きょ")).toBeTruthy();
    fireEvent.keyDown(window, { key: "]" });
    expect(screen.getByText("当前 Mora：う")).toBeTruthy();
  });

  it("REQ-MORA-SHORTCUT-02 selects the previous Mora with the default left bracket", () => {
    renderEditor();
    fireEvent.keyDown(window, { key: "[" });
    expect(screen.getByText("当前 Mora：う")).toBeTruthy();
    fireEvent.keyDown(window, { key: "[" });
    expect(screen.getByText("当前 Mora：きょ")).toBeTruthy();
  });

  it("REQ-MORA-SHORTCUT-04 moves focus so arrows nudge the newly selected Mora", () => {
    const onChange = vi.fn();
    const onSeek = vi.fn();
    renderEditor({ onChange, onSeek });
    const firstMora = screen.getByRole("button", { name: "きょ" });
    fireEvent.focus(firstMora);
    fireEvent.keyDown(firstMora, { key: "]" });

    const secondMora = screen.getByRole("button", { name: "う" });
    expect(document.activeElement).toBe(secondMora);
    fireEvent.keyDown(secondMora, { key: "ArrowRight" });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({
        units: expect.arrayContaining([expect.objectContaining({
          moras: expect.arrayContaining([
            expect.objectContaining({ reading: "きょ", startMs: 1000 }),
            expect.objectContaining({ reading: "う", startMs: 1610 }),
          ]),
        })]),
      })]),
    }));
    expect(onSeek).toHaveBeenCalledWith(1510);
  });

  it("REQ-MORA-KEY-01 nudges a focused Mora start instead of seeking the video", () => {
    const onChange = vi.fn();
    const onSeek = vi.fn();
    renderEditor({ onChange, onSeek });
    const mora = screen.getByRole("button", { name: "う" });
    fireEvent.focus(mora);
    fireEvent.keyDown(mora, { key: "ArrowRight" });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({
        units: expect.arrayContaining([expect.objectContaining({
          moras: expect.arrayContaining([expect.objectContaining({
            reading: "う",
            startMs: 1610,
          })]),
        })]),
      })]),
    }));
    expect(onSeek).toHaveBeenCalledWith(1510);
  });

  it("REQ-TIME-07 uses a smaller mouse hit area than the density threshold", () => {
    const { container } = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    const boundary = container.querySelector<HTMLElement>('[data-mora-boundary="0"]');
    expect(boundary?.style.width).toBe("12px");
    expect(container.querySelector('[data-mora-timeline="true"]')?.getAttribute("data-boundary-gap-px")).toBe("20");
  });

  it("REQ-OPERATION-01 separates whole-line controls from the Mora color blocks", () => {
    const { container } = renderEditor();
    expect(container.querySelector('[data-line-move="true"]')?.getAttribute("title")).toBe("整句平移");
    expect(container.querySelector('[data-line-edge="start"]')?.getAttribute("title")).toBe("整句开始（按比例拉伸）");
    expect(container.querySelector('[data-mora-segment]')?.getAttribute("title")).toContain("选择 Mora");
  });

  it("REQ-OPERATION-02 nudges the focused whole-line move control with arrow keys", () => {
    const onChange = vi.fn();
    const onSeek = vi.fn();
    const { container } = renderEditor({ onChange, onSeek });
    const moveControl = container.querySelector<HTMLElement>('[data-line-move="true"]');

    fireEvent.keyDown(moveControl!, { key: "ArrowRight" });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({ startMs: 1010, endMs: 2010 })]),
    }));
    expect(onSeek).toHaveBeenCalledWith(910);
  });

  it("REQ-BULK-01 selects a continuous Mora range with Shift and distributes it", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    fireEvent.click(screen.getByRole("button", { name: "う" }), { shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: /选中字数平分/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({
        units: expect.arrayContaining([expect.objectContaining({
          moras: expect.arrayContaining([
            expect.objectContaining({ reading: "きょ", startMs: 1000, endMs: 1500 }),
            expect.objectContaining({ reading: "う", startMs: 1500, endMs: 2000 }),
          ]),
        })]),
      })]),
    }));
  });

  it("REQ-BULK-02 exposes independent first and last Mora nudges", () => {
    const onChange = vi.fn();
    renderEditor({ onChange });
    fireEvent.click(screen.getByRole("button", { name: "句首字延后" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      lines: expect.arrayContaining([expect.objectContaining({
        startMs: 1010,
        units: expect.arrayContaining([expect.objectContaining({
          moras: expect.arrayContaining([expect.objectContaining({ reading: "きょ", startMs: 1010, endMs: 1600 })]),
        })]),
      })]),
    }));
  });

  it("REQ-STYLE-LAYOUT-02 lets the timeline fill the timing card content width", () => {
    const { container } = renderEditor();
    const wrapper = container.querySelector('[data-timeline-track-wrapper="true"]');
    expect(wrapper?.className).toContain("w-full");
    expect(wrapper?.className).not.toContain("px-2");
  });

  it("REQ-STYLE-LAYOUT-03 restores the flat timeline styling from the requested baseline", () => {
    const { container } = renderEditor();
    const track = container.querySelector('[data-mora-timeline="true"]');
    const mora = container.querySelector('[data-mora-segment]');
    expect(track?.className).toContain("bg-muted/40");
    expect(track?.className).not.toContain("shadow");
    expect(mora?.className).not.toContain("rounded");
    expect(mora?.className).not.toContain("shadow");
  });

  it("REQ-OPERATION-03 renders the three whole-line controls as simple dot handles", () => {
    const { container } = renderEditor();
    expect(container.querySelectorAll('[data-line-control-dot]')).toHaveLength(3);
    expect(container.querySelector('[data-line-move="true"]')?.className).not.toContain("rounded-full");
  });

  it("REQ-DENSITY-03 renders a sufficiently spaced boundary as directly draggable", async () => {
    const rectSpy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 400 } as DOMRect);
    try {
      const { container } = renderEditor();
      await waitFor(() => expect(container.querySelector('[data-density-mode="direct"]')).toBeTruthy());
    } finally {
      rectSpy.mockRestore();
    }
  });

  it("REQ-DENSITY-04 uses the larger boundary gap for touch input", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({ matches: true })),
    });
    const { container } = renderEditor();
    expect(container.querySelector('[data-mora-timeline="true"]')?.getAttribute("data-boundary-gap-px")).toBe("32");
  });

  it("REQ-LAYOUT-01 omits duplicate line-start nudge buttons", () => {
    renderEditor();
    expect(screen.queryByRole("button", { name: "句首提前" })).toBeNull();
  });

  it("REQ-LAYOUT-02 omits duplicate line-end nudge buttons", () => {
    renderEditor();
    expect(screen.queryByRole("button", { name: "句尾延后" })).toBeNull();
  });

  it("REQ-LAYOUT-03 keeps whole-line nudge buttons", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: "整句提前" })).toBeTruthy();
  });

  it("REQ-LAYOUT-04 keeps all five timing step options", () => {
    renderEditor();
    expect(screen.getByLabelText("微调步长").querySelectorAll("option")).toHaveLength(5);
  });

  it("REQ-LAYOUT-05 places timing controls in one adjustment row", () => {
    const { container } = renderEditor();
    const row = container.querySelector('[data-timing-adjustment-row="true"]');
    expect(row?.querySelector('[data-timeline-offset-group="true"]')).toBeTruthy();
  });

  it("REQ-LAYOUT-06 shifts the offset group right on desktop", () => {
    const { container } = renderEditor();
    expect(container.querySelector('[data-timeline-offset-group="true"]')?.className).toContain("md:ml-auto");
  });

  it("REQ-LAYOUT-07 lets the timing adjustment row wrap", () => {
    const { container } = renderEditor();
    expect(container.querySelector('[data-timing-adjustment-row="true"]')?.className).toContain("flex-wrap");
  });
});
