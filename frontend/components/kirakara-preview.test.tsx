import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { rememberLocalVideo } from "@/lib/local-media-session";

async function loadPreview() {
  const modulePath = "./kirakara-preview";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("KirakaraPreview", () => {
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
});
