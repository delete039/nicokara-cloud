import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { rememberLocalVideo } from "@/lib/local-media-session";

async function loadPreview() {
  const modulePath = "./kirakara-preview";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("KirakaraPreview", () => {
  it("keeps a running preview loop on the latest frame callback", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    expect(preview.createPreviewFrameLoop).toBeTypeOf("function");
    if (typeof preview.createPreviewFrameLoop !== "function") return;

    const scheduledFrames: FrameRequestCallback[] = [];
    const oldTimelineDraw = vi.fn();
    const adjustedTimelineDraw = vi.fn();
    const loop = preview.createPreviewFrameLoop({
      draw: oldTimelineDraw,
      isPlaying: () => true,
      requestFrame: (callback: FrameRequestCallback) => {
        scheduledFrames.push(callback);
        return scheduledFrames.length;
      },
      cancelFrame: vi.fn(),
    });

    loop.start();
    expect(oldTimelineDraw).toHaveBeenCalledTimes(1);
    expect(scheduledFrames).toHaveLength(1);

    loop.setDraw(adjustedTimelineDraw);
    expect(adjustedTimelineDraw).toHaveBeenCalledTimes(1);

    scheduledFrames.shift()?.(16);
    expect(oldTimelineDraw).toHaveBeenCalledTimes(1);
    expect(adjustedTimelineDraw).toHaveBeenCalledTimes(2);
  });

  it("allows a refreshed job page to reconnect the original local video", async () => {
    const preview = await loadPreview();
    expect(preview, "Kirakara preview component should exist").not.toBeNull();
    if (!preview) return;

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview jobId="job-1" expectedVideoName="song.mp4" />,
    );

    expect(html).toContain("浏览器本地预览");
    expect(html).toContain("Kirakara 引擎");
    expect(html).toContain("text-base");
    expect(html).toContain("重新选择原视频");
    expect(html).toContain("song.mp4");
    expect(html).toContain("时间轴调整会自动保存在此浏览器");
  });

  it("shows the engine name only in the preview heading, not over the video", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-with-video", new File(["video"], "song.mp4"));

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview
        jobId="job-with-video"
        expectedVideoName="song.mp4"
      />,
    );

    expect(html.match(/Kirakara 引擎/g)).toHaveLength(1);
  });

  it("uses a DOM lyric overlay for realtime preview instead of canvas", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-dom-preview", new File(["video"], "song.mp4"));

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview
        jobId="job-dom-preview"
        expectedVideoName="song.mp4"
      />,
    );

    expect(html).toContain('data-kirakara-dom-preview="true"');
    expect(html).not.toContain("<canvas");
  });

  it("REQ-PLACEMENT-07 gives the video the full workbench width", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-wide-video", new File(["video"], "song.mp4"));

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview jobId="job-wide-video" expectedVideoName="song.mp4" />,
    );

    expect(html).toMatch(/data-kirakara-preview-panel="true"[^>]+lg:col-span-2 lg:row-start-1/);
  });

  it("REQ-PLACEMENT-08 places the lyric panel left of the timeline", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-editor-columns", new File(["video"], "song.mp4"));

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview jobId="job-editor-columns" expectedVideoName="song.mp4" />,
    );

    expect(html).toMatch(/data-kirakara-controls-panel="true"[^>]+lg:col-start-1 lg:row-start-2/);
    expect(html).toMatch(/data-kirakara-timeline-panel="true"[^>]+lg:col-start-2 lg:row-start-2/);
  });

  it("REQ-PLACEMENT-06 places a full-width export card below the timeline", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-export-panel", new File(["video"], "song.mp4"));

    const html = renderToStaticMarkup(
      <preview.KirakaraPreview jobId="job-export-panel" expectedVideoName="song.mp4" />,
    );

    // The export section follows the workbench rather than depending on its
    // two-column grid, so it remains available when no local video is selected.
    expect(html).toContain('</div></div><section data-kirakara-export-panel="true"');
    expect(html.indexOf('data-kirakara-export-panel="true"'))
      .toBeGreaterThan(html.indexOf('data-kirakara-timeline-panel="true"'));
  });
});

describe("subtitle playback control requirements", () => {
  it("REQ-SELECT-02 seeks without calling play or pause", async () => {
    const preview = await loadPreview();
    const video = { currentTime: 0, duration: 5, play: vi.fn(), pause: vi.fn() };
    preview?.seekVideoWithoutPlaybackChange(video, 2900);
    expect(video.play).not.toHaveBeenCalled();
    expect(video.pause).not.toHaveBeenCalled();
  });

  it("REQ-PLAY-03 preserves a playing video's state while seeking", async () => {
    const preview = await loadPreview();
    const video = { currentTime: 1, duration: 5, pause: vi.fn() };
    preview?.seekVideoWithoutPlaybackChange(video, 2900);
    expect(video.pause).not.toHaveBeenCalled();
  });

  it("REQ-RATE-02 decreases the playback rate for X", async () => {
    const preview = await loadPreview();
    const editing = await import("@/lib/timeline-editing");
    expect(preview?.playbackRateAfterShortcut(editing.PlaybackShortcut.RateDown, 1, 0.9)).toBe(0.9);
  });

  it("REQ-RATE-03 increases the playback rate for C", async () => {
    const preview = await loadPreview();
    const editing = await import("@/lib/timeline-editing");
    expect(preview?.playbackRateAfterShortcut(editing.PlaybackShortcut.RateUp, 1, 0.9)).toBe(1.1);
  });

  it("REQ-RATE-04-A toggles from 1.0x to the last non-default rate", async () => {
    const preview = await loadPreview();
    const editing = await import("@/lib/timeline-editing");
    expect(preview?.playbackRateAfterShortcut(editing.PlaybackShortcut.RateToggle, 1, 0.8)).toBe(0.8);
  });

  it("REQ-RATE-04-B toggles a non-default rate back to 1.0x", async () => {
    const preview = await loadPreview();
    const editing = await import("@/lib/timeline-editing");
    expect(preview?.playbackRateAfterShortcut(editing.PlaybackShortcut.RateToggle, 0.8, 0.8)).toBe(1);
  });

  it("REQ-RATE-06 defines a one-second playback rate notice", async () => {
    const preview = await loadPreview();
    expect(preview?.RATE_NOTICE_DURATION_MS).toBe(1000);
  });

  it("REQ-RATE-07 renders the playback rate notice as a DOM overlay", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    const html = renderToStaticMarkup(<preview.PlaybackRateNotice rate={0.8} />);
    expect(html).toContain('data-playback-rate-notice="true"');
  });

  it("REQ-RATE-11 initializes the page playback rate at 1.0x", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-rate-default", new File(["video"], "song.mp4"));
    const html = renderToStaticMarkup(<preview.KirakaraPreview jobId="job-rate-default" expectedVideoName="song.mp4" />);
    expect(html).toContain('<option value="1" selected="">1.0×</option>');
  });

  it("REQ-VIDEO-TIME-01 renders current video time beside playback controls", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-time", new File(["video"], "song.mp4"));
    const html = renderToStaticMarkup(<preview.KirakaraPreview jobId="job-time" expectedVideoName="song.mp4" />);
    expect(html).toContain('data-current-video-time="true"');
  });

  it("REQ-VIDEO-TIME-04 renders video time as read-only output", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-time-output", new File(["video"], "song.mp4"));
    const html = renderToStaticMarkup(<preview.KirakaraPreview jobId="job-time-output" expectedVideoName="song.mp4" />);
    expect(html).toContain('<output data-current-video-time="true"');
  });

  it("REQ-VIDEO-TIME-05 uses tabular numerals for current video time", async () => {
    const preview = await loadPreview();
    expect(preview).not.toBeNull();
    if (!preview) return;
    rememberLocalVideo("job-time-style", new File(["video"], "song.mp4"));
    const html = renderToStaticMarkup(<preview.KirakaraPreview jobId="job-time-style" expectedVideoName="song.mp4" />);
    expect(html).toMatch(/data-current-video-time="true"[^>]+tabular-nums/);
  });
});
