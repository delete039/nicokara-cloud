/* @vitest-environment jsdom */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { rememberLocalVideo } from "@/lib/local-media-session";

vi.mock("@/services/api", () => ({
  ApiRequestError: class extends Error {},
  getTimeline: vi.fn(async () => ({
    source_revision: "revision-1",
    confidence: 1,
    warnings: [],
    lines: [
      {
        surface: "今日",
        reading: "きょう",
        start_ms: 1000,
        end_ms: 2000,
        confidence: 1,
        tokens: [{
          surface: "今日",
          reading: "きょう",
          start_ms: 1000,
          end_ms: 2000,
          confidence: 1,
          moras: [
            { reading: "きょ", start_ms: 1000, end_ms: 1600, matched: true, confidence: 1 },
            { reading: "う", start_ms: 1600, end_ms: 2000, matched: true, confidence: 1 },
          ],
        }],
      },
      {
        surface: "明日",
        reading: "あした",
        start_ms: 3000,
        end_ms: 4000,
        confidence: 1,
        tokens: [{
          surface: "明日",
          reading: "あした",
          start_ms: 3000,
          end_ms: 4000,
          confidence: 1,
          moras: [],
        }],
      },
    ],
  })),
  getTimelineReviewDraft: vi.fn(async () => null),
  saveTimelineReviewDraft: vi.fn(async () => ({ saved_at: "now" })),
}));

vi.mock("@/lib/review-draft-store", () => ({
  compatibleTimelineDraft: vi.fn(() => null),
  loadBrowserReviewDraft: vi.fn(async () => null),
  saveBrowserReviewDraft: vi.fn(async () => undefined),
}));

vi.mock("@/lib/kirakara-capabilities", () => ({
  detectKirakaraCapabilities: vi.fn(async () => ({ preview: true, export: false, profile: null })),
  kirakaraSupportMessage: vi.fn(() => ""),
}));

vi.mock("@/components/kirakara-render-actions", () => ({
  KirakaraRenderActions: ({ timeline }: {
    timeline: { lines: Array<{ units: Array<{ romajiMoras?: string[] }> }> };
  }) => (
    <div
      data-testid="render-actions"
      data-romaji-enabled={String(Boolean(timeline.lines[0]?.units[0]?.romajiMoras?.length))}
    />
  ),
}));

import { KirakaraPreview } from "./kirakara-preview";

function installVideoBehavior(video: HTMLVideoElement, initiallyPaused = true) {
  let paused = initiallyPaused;
  Object.defineProperty(video, "paused", { configurable: true, get: () => paused });
  Object.defineProperty(video, "duration", { configurable: true, value: 5 });
  video.play = vi.fn(async () => {
    paused = false;
    fireEvent.play(video);
  });
  video.pause = vi.fn(() => {
    paused = true;
    fireEvent.pause(video);
  });
  return {
    setPaused(value: boolean) {
      paused = value;
    },
  };
}

async function renderWorkbench(jobId: string) {
  rememberLocalVideo(jobId, new File(["video"], "song.mp4", { type: "video/mp4" }));
  const rendered = render(<KirakaraPreview jobId={jobId} expectedVideoName="song.mp4" />);
  await screen.findByRole("button", { name: "1. 今日" });
  const video = rendered.container.querySelector("video") as HTMLVideoElement;
  expect(video).toBeTruthy();
  return { ...rendered, video };
}

describe("KirakaraPreview browser behavior", () => {
  beforeEach(() => {
    vi.useRealTimers();
    Element.prototype.scrollIntoView = vi.fn();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    });
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:video") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    Object.defineProperty(globalThis, "requestAnimationFrame", { configurable: true, writable: true, value: vi.fn(() => 1) });
    Object.defineProperty(globalThis, "cancelAnimationFrame", { configurable: true, writable: true, value: vi.fn() });
    Object.defineProperty(globalThis, "ResizeObserver", {
      configurable: true,
      writable: true,
      value: class {
        observe() {}
        disconnect() {}
      },
    });
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows and hides the preview romaji layer with the double-ruby checkbox", async () => {
    const { container } = await renderWorkbench("preview-romaji-toggle");
    const checkbox = screen.getByRole("checkbox", {
      name: "双注音（假名 + 罗马音）",
    }) as HTMLInputElement;
    const canvas = container.querySelector('[data-kirakara-canvas-preview="true"]');
    const locateButton = screen.getByRole("button", { name: "定位歌词" });

    expect(checkbox.checked).toBe(false);
    expect(
      locateButton.compareDocumentPosition(checkbox) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(checkbox.closest("div")?.className).toContain("ml-auto");
    expect(screen.queryByLabelText("罗马音位置")).toBeNull();
    await waitFor(() => expect(canvas?.getAttribute("data-kirakara-romaji-enabled")).toBe("false"));
    await waitFor(() => expect(screen.getByTestId("render-actions").getAttribute("data-romaji-enabled")).toBe("false"));
    fireEvent.click(checkbox);
    const position = screen.getByLabelText("罗马音位置") as HTMLSelectElement;
    expect(position.value).toBe("above");
    expect(
      locateButton.compareDocumentPosition(position) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(position.closest("div")).toBe(checkbox.closest("div"));
    await waitFor(() => expect(canvas?.getAttribute("data-kirakara-romaji-enabled")).toBe("true"));
    await waitFor(() => expect(screen.getByTestId("render-actions").getAttribute("data-romaji-enabled")).toBe("true"));
    expect(canvas?.getAttribute("data-kirakara-romaji-position")).toBe("above");
    fireEvent.change(position, { target: { value: "below" } });
    await waitFor(() => expect(canvas?.getAttribute("data-kirakara-romaji-position")).toBe("below"));
    fireEvent.click(checkbox);
    expect(screen.queryByLabelText("罗马音位置")).toBeNull();
  });

  it("REQ-FOLLOW-04 does not save a timeline edit during automatic following", async () => {
    const api = await import("@/services/api");
    const { video } = await renderWorkbench("follow-no-save");
    const behavior = installVideoBehavior(video, false);
    behavior.setPaused(false);
    video.currentTime = 3.1;
    fireEvent.timeUpdate(video);
    expect(api.saveTimelineReviewDraft).not.toHaveBeenCalled();
  });

  it("REQ-PIN-01 keeps the selected editing line pinned while playback moves", async () => {
    const { video, container } = await renderWorkbench("pinned-editing-line");
    installVideoBehavior(video, false);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    video.currentTime = 1.1;
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(screen.getByRole("button", { name: /1\. 今日/ }).getAttribute("aria-current")).toBe("true"));
    expect(screen.getByRole("button", { name: "2. 明日" }).getAttribute("data-editing-line")).toBe("true");
    expect(container.querySelector('[aria-label="当前歌词行时间轴：明日"]')).toBeTruthy();
  });

  it("REQ-PIN-02 locates the editor on the current playback line without seeking", async () => {
    const { video, container } = await renderWorkbench("locate-playback-line");
    installVideoBehavior(video, false);
    video.currentTime = 3.1;
    fireEvent.timeUpdate(video);
    fireEvent.click(screen.getByRole("button", { name: "定位歌词" }));
    expect(container.querySelector('[aria-label="当前歌词行时间轴：明日"]')).toBeTruthy();
    expect(video.currentTime).toBe(3.1);
  });

  it("REQ-PIN-03 focuses the video after a lyric is clicked", async () => {
    const { video } = await renderWorkbench("lyric-focuses-video");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    expect(document.activeElement).toBe(video);
  });

  it("REQ-LIST-01 renders a persistent scrollable lyric list", async () => {
    const { container } = await renderWorkbench("scrollable-lyrics");
    expect(container.querySelector('[data-lyric-navigator="true"]')?.className).toContain("overflow-y-auto");
  });

  it("REQ-LIST-05 hides both lyric scrollbar tracks", async () => {
    const { container } = await renderWorkbench("hidden-lyric-scrollbars");
    const navigator = container.querySelector('[data-lyric-navigator="true"]');
    expect(navigator?.className).toContain("[scrollbar-width:none]");
    expect(navigator?.className).toContain("[&::-webkit-scrollbar]:hidden");
  });

  it("REQ-LIST-02 places the lyric tabs after the timeline for vertical layouts", async () => {
    const { container } = await renderWorkbench("vertical-lyrics");
    const timelinePanel = container.querySelector('[data-kirakara-timeline-panel="true"]');
    const controlsPanel = container.querySelector('[data-kirakara-controls-panel="true"]');
    const position = timelinePanel && controlsPanel
      ? timelinePanel.compareDocumentPosition(controlsPanel)
      : 0;
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("REQ-LIST-03-A displays lyric line numbers and text", async () => {
    await renderWorkbench("numbered-lyrics");
    expect(screen.getByRole("button", { name: "2. 明日" })).toBeTruthy();
  });

  it("REQ-LIST-03-B marks the playback lyric independently", async () => {
    const { video } = await renderWorkbench("playback-lyric-highlight");
    installVideoBehavior(video, false);
    video.currentTime = 3.1;
    fireEvent.timeUpdate(video);
    expect(screen.getByRole("button", { name: /2\. 明日/ }).getAttribute("aria-current")).toBe("true");
  });

  it("REQ-LIST-04 scrolls the current playback lyric into view", async () => {
    const { video, container } = await renderWorkbench("playback-lyric-scroll");
    installVideoBehavior(video, false);
    const navigator = container.querySelector<HTMLElement>('[data-lyric-navigator="true"]');
    const secondLine = screen.getByRole("button", { name: "2. 明日" });
    expect(navigator).toBeTruthy();
    if (!navigator) return;
    navigator.scrollTop = 10;
    navigator.getBoundingClientRect = vi.fn(() => ({ top: 100, bottom: 200 }) as DOMRect);
    secondLine.getBoundingClientRect = vi.fn(() => ({ top: 220, bottom: 240 }) as DOMRect);
    video.currentTime = 3.1;
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(navigator.scrollTop).toBe(50));
  });

  it("REQ-SCROLL-02 keeps a clicked visible lyric at the current scroll position", async () => {
    const { container } = await renderWorkbench("visible-lyric-keeps-scroll");
    const navigator = container.querySelector<HTMLElement>('[data-lyric-navigator="true"]');
    const secondLine = screen.getByRole("button", { name: "2. 明日" });
    expect(navigator).toBeTruthy();
    if (!navigator) return;
    navigator.scrollTop = 300;
    navigator.getBoundingClientRect = vi.fn(() => ({ top: 100, bottom: 300 }) as DOMRect);
    secondLine.getBoundingClientRect = vi.fn(() => ({ top: 140, bottom: 180 }) as DOMRect);
    fireEvent.click(secondLine);
    await waitFor(() => expect(secondLine.getAttribute("data-editing-line")).toBe("true"));
    expect(navigator.scrollTop).toBe(300);
  });

  it("REQ-SCROLL-01 does not scroll the page when playback advances", async () => {
    const { video } = await renderWorkbench("playback-keeps-page-position");
    installVideoBehavior(video, false);
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    video.currentTime = 3.1;
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(screen.getByRole("button", { name: /2\. 明日/ }).getAttribute("aria-current")).toBe("true"));
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it("REQ-SELECT-01 seeks a manually selected lyric with preview lead", async () => {
    const { video } = await renderWorkbench("selection-preview-lead");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    expect(video.currentTime).toBe(2.9);
  });

  it("REQ-LEAD-01 uses the configured preview lead for lyric selection", async () => {
    const { video } = await renderWorkbench("configured-selection-lead");
    installVideoBehavior(video);
    fireEvent.change(screen.getByLabelText("复听提前量（ms）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    expect(video.currentTime).toBe(2.75);
  });

  it("REQ-LEAD-06 does not save a timeline edit when selecting a lyric", async () => {
    const api = await import("@/services/api");
    const { video } = await renderWorkbench("selection-no-save");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    expect(api.saveTimelineReviewDraft).not.toHaveBeenCalled();
  });

  it("REQ-PLAY-01 keeps selection from starting paused video", async () => {
    const { video } = await renderWorkbench("selection-paused");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    expect(video.play).not.toHaveBeenCalled();
  });

  it("REQ-PLAY-02 keeps a user-paused video paused after loop positioning", async () => {
    const { video } = await renderWorkbench("loop-paused");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.click(await screen.findByRole("button", { name: "单句循环试听" }));
    expect(video.play).not.toHaveBeenCalled();
  });

  it("REQ-PLAY-05 changes loop range without changing playback state", async () => {
    const { video } = await renderWorkbench("loop-state");
    installVideoBehavior(video, false);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.click(await screen.findByRole("button", { name: "单句循环试听" }));
    expect(video.pause).not.toHaveBeenCalled();
  });

  it("REQ-LEAD-12 does not let an active loop override Mora preview lead", async () => {
    const { video } = await renderWorkbench("loop-keeps-mora-preview-lead");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.click(await screen.findByRole("button", { name: "单句循环试听" }));
    fireEvent.click(screen.getByRole("button", { name: "う" }));
    const input = screen.getByLabelText("Mora 开始（秒）");
    fireEvent.change(input, { target: { value: "1.700" } });
    fireEvent.blur(input);
    expect(video.currentTime).toBe(1.6);
  });

  it("REQ-RATE-01 uses a playback rate select", async () => {
    await renderWorkbench("rate-select");
    expect(screen.getByLabelText("播放倍速").tagName).toBe("SELECT");
  });

  it("REQ-RATE-05 keeps shortcut and select on the same playback rate state", async () => {
    await renderWorkbench("rate-shared");
    fireEvent.change(screen.getByLabelText("播放倍速"), { target: { value: "0.8" } });
    fireEvent.keyDown(window, { key: "c" });
    await waitFor(() => expect((screen.getByLabelText("播放倍速") as HTMLSelectElement).value).toBe("0.9"));
  });

  it("REQ-RATE-06 hides the playback rate notice after one second", async () => {
    await renderWorkbench("rate-notice");
    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText("播放倍速"), { target: { value: "0.8" } });
    expect(document.querySelector('[data-playback-rate-notice="true"]')?.textContent).toBe("0.8×");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(document.querySelector('[data-playback-rate-notice="true"]')).toBeNull();
  });

  it("REQ-RATE-08 ignores playback shortcuts from focused text inputs", async () => {
    await renderWorkbench("rate-input-focus");
    const input = screen.getByLabelText("复听提前量（ms）");
    fireEvent.keyDown(input, { key: "x" });
    expect((screen.getByLabelText("播放倍速") as HTMLSelectElement).value).toBe("1");
  });

  it("REQ-RATE-12 reapplies the page playback rate when video metadata loads", async () => {
    const { video } = await renderWorkbench("rate-video-change");
    installVideoBehavior(video);
    fireEvent.change(screen.getByLabelText("播放倍速"), { target: { value: "0.8" } });
    video.playbackRate = 1;
    fireEvent.loadedMetadata(video);
    expect(video.playbackRate).toBe(0.8);
  });

  it("REQ-RATE-14 does not persist playback rate in localStorage", async () => {
    await renderWorkbench("rate-memory-only");
    fireEvent.change(screen.getByLabelText("播放倍速"), { target: { value: "0.8" } });
    expect(Object.keys(window.localStorage)).toEqual([]);
  });

  it("REQ-SHORTCUT-07 renders all line, Mora, and playback-rate shortcut settings", async () => {
    await renderWorkbench("shortcut-settings");
    expect(screen.getAllByLabelText(/^快捷键：/)).toHaveLength(9);
    expect((screen.getByLabelText("快捷键：上一句") as HTMLInputElement).value).toBe("U");
    expect((screen.getByLabelText("快捷键：上一个 Mora") as HTMLInputElement).value).toBe("[");
    expect((screen.getByLabelText("快捷键：下一个 Mora") as HTMLInputElement).value).toBe("]");
    expect((screen.getByLabelText("快捷键：提高倍速") as HTMLInputElement).value).toBe("C");
  });

  it("REQ-SHORTCUT-08 locates the previous lyric with U", async () => {
    const { video, container } = await renderWorkbench("shortcut-previous");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "2. 明日" }));
    fireEvent.keyDown(window, { key: "u" });
    expect(container.querySelector('[aria-label="当前歌词行时间轴：今日"]')).toBeTruthy();
    expect(video.currentTime).toBe(0.9);
  });

  it("REQ-SHORTCUT-09 locates the next lyric with I", async () => {
    const { video, container } = await renderWorkbench("shortcut-next");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.keyDown(window, { key: "i" });
    expect(container.querySelector('[aria-label="当前歌词行时间轴：明日"]')).toBeTruthy();
    expect(video.currentTime).toBe(2.9);
  });

  it("REQ-SHORTCUT-10 replays the current lyric with O without resuming a paused video", async () => {
    const { video } = await renderWorkbench("shortcut-replay");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    video.currentTime = 1.7;
    fireEvent.keyDown(window, { key: "o" });
    expect(video.currentTime).toBe(1);
    expect(video.play).not.toHaveBeenCalled();
  });

  it("REQ-SHORTCUT-11 toggles the current lyric loop with P", async () => {
    const { video } = await renderWorkbench("shortcut-loop");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.keyDown(window, { key: "p" });
    await waitFor(() => expect(screen.getByRole("button", { name: "单句循环试听" }).getAttribute("aria-pressed")).toBe("true"));
    expect(video.play).not.toHaveBeenCalled();
  });

  it("REQ-SHORTCUT-12 applies a customized playback-rate shortcut", async () => {
    await renderWorkbench("shortcut-custom-rate");
    fireEvent.keyDown(screen.getByLabelText("快捷键：提高倍速"), { key: "v" });
    fireEvent.keyDown(window, { key: "v" });
    expect((screen.getByLabelText("播放倍速") as HTMLSelectElement).value).toBe("1.1");
    expect(window.localStorage.getItem("nicokara.timeline.playbackShortcuts")).toContain('"rate-up":"v"');
  });

  it("REQ-SET-03 restores preview lead to 100ms", async () => {
    await renderWorkbench("lead-default");
    fireEvent.change(screen.getByLabelText("复听提前量（ms）"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "恢复默认值" }));
    expect((screen.getByLabelText("复听提前量（ms）") as HTMLInputElement).value).toBe("100");
  });

  it("REQ-SET-01 renders timing settings inside the timeline card", async () => {
    const { container } = await renderWorkbench("timing-settings-placement");
    expect(container.querySelector('[data-timing-settings="true"]')?.closest('[data-kirakara-timeline-panel="true"]')).toBeTruthy();
  });

  it("REQ-LEAD-10 updates and saves preview lead on each input change", async () => {
    await renderWorkbench("lead-immediate");
    fireEvent.change(screen.getByLabelText("复听提前量（ms）"), { target: { value: "250" } });
    expect(window.localStorage.getItem("nicokara.timeline.previewLeadMs")).toBe("250");
  });

  it("REQ-LEAD-09-A clamps a negative preview lead in the settings input", async () => {
    await renderWorkbench("lead-negative");
    fireEvent.change(screen.getByLabelText("复听提前量（ms）"), { target: { value: "-1" } });
    expect((screen.getByLabelText("复听提前量（ms）") as HTMLInputElement).value).toBe("0");
  });

  it("REQ-LEAD-09-B clamps an oversized preview lead in the settings input", async () => {
    await renderWorkbench("lead-oversized");
    fireEvent.change(screen.getByLabelText("复听提前量（ms）"), { target: { value: "2001" } });
    expect((screen.getByLabelText("复听提前量（ms）") as HTMLInputElement).value).toBe("2000");
  });

  it("REQ-VIDEO-TIME-03 refreshes current time on a video timeupdate event", async () => {
    const { video } = await renderWorkbench("video-time-update");
    installVideoBehavior(video);
    video.currentTime = 18.8;
    fireEvent.timeUpdate(video);
    expect(screen.getByLabelText("当前视频时间").textContent).toBe("18.800");
  });

  it("REQ-SEEK-04 seeks the video backward from an unfocused page", async () => {
    const { video } = await renderWorkbench("page-arrow-backward");
    installVideoBehavior(video);
    video.currentTime = 5;
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(video.currentTime).toBe(0);
  });

  it("REQ-SEEK-05 seeks the video forward from an unfocused page", async () => {
    const { video } = await renderWorkbench("page-arrow-forward");
    installVideoBehavior(video);
    video.currentTime = 0;
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(video.currentTime).toBe(5);
  });

  it("REQ-KEY-03 toggles video playback while a timing boundary is focused", async () => {
    const { video } = await renderWorkbench("boundary-space-playback");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    const boundary = screen.getByRole("button", { name: "调整第 1 个 Mora 分界" });
    boundary.focus();
    fireEvent.keyDown(boundary, { key: " " });
    expect(video.play).toHaveBeenCalledTimes(1);
  });

  it("REQ-KEY-04 changes playback rate while a timing boundary is focused", async () => {
    const { video } = await renderWorkbench("boundary-rate-shortcut");
    installVideoBehavior(video);
    fireEvent.click(screen.getByRole("button", { name: "1. 今日" }));
    fireEvent.click(screen.getByRole("button", { name: "きょ" }));
    const boundary = screen.getByRole("button", { name: "调整第 1 个 Mora 分界" });
    boundary.focus();
    fireEvent.keyDown(boundary, { key: "x" });
    expect((screen.getByLabelText("播放倍速") as HTMLSelectElement).value).toBe("0.9");
  });

  it("REQ-PLACEMENT-01 switches the right-side panel between lyrics and subtitle style", async () => {
    await renderWorkbench("side-tabs");
    expect(screen.getByRole("tab", { name: "滚动歌词" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "字幕样式" }));
    expect(screen.getByRole("heading", { name: "字幕样式" })).toBeTruthy();
  });

  it("REQ-PLACEMENT-02 orders the timeline before the side tabs in vertical flow", async () => {
    const { container } = await renderWorkbench("vertical-panel-order");
    const timelinePanel = container.querySelector('[data-kirakara-timeline-panel="true"]');
    const controlsPanel = container.querySelector('[data-kirakara-controls-panel="true"]');
    const position = timelinePanel && controlsPanel
      ? timelinePanel.compareDocumentPosition(controlsPanel)
      : 0;
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("REQ-EXPORT-01 keeps download actions in the export card", async () => {
    const { container } = await renderWorkbench("separate-export-card");
    const downloads = container.querySelector('[data-reviewed-data-downloads="true"]');
    expect(downloads?.closest('[data-kirakara-export-panel="true"]')).toBeTruthy();
    expect(downloads?.closest('[data-kirakara-controls-panel="true"]')).toBeNull();
    expect(screen.getByRole("heading", { name: "导出" })).toBeTruthy();
  });
});
