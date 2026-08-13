import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

async function loadProgressComponent() {
  const modulePath = "./mobile-submission-progress";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("MobileSubmissionProgress", () => {
  it("shows local extraction progress and a cancel command", async () => {
    const progress = await loadProgressComponent();
    expect(progress, "mobile progress component should exist").not.toBeNull();
    if (!progress) return;

    const html = renderToStaticMarkup(
      <progress.MobileSubmissionProgress
        state={{ stage: "EXTRACTING_AUDIO", progress: 36 }}
        onCancel={vi.fn()}
      />,
    );

    expect(html).toContain("正在本地提取音频");
    expect(html).toContain("36%");
    expect(html).toContain("取消本地处理");
    expect(html).toContain("视频不会上传");
  });

  it("explains that an incompatible audio track falls back to video", async () => {
    const progress = await loadProgressComponent();
    expect(progress).not.toBeNull();
    if (!progress) return;

    const html = renderToStaticMarkup(
      <progress.MobileSubmissionProgress
        state={{ stage: "FALLBACK_VIDEO", progress: 0 }}
      />,
    );

    expect(html).toContain("已切换完整视频上传");
    expect(html).toContain("不兼容");
    expect(html).not.toContain("取消本地处理");
  });

  it("explains chunk retries and resume behavior during audio upload", async () => {
    const progress = await loadProgressComponent();
    expect(progress).not.toBeNull();
    if (!progress) return;

    const html = renderToStaticMarkup(
      <progress.MobileSubmissionProgress
        state={{ stage: "UPLOADING_AUDIO", progress: 64 }}
        onCancel={vi.fn()}
      />,
    );

    expect(html).toContain("正在上传音频");
    expect(html).toContain("8 MiB 分片");
    expect(html).toContain("自动重试");
    expect(html).toContain("继续");
    expect(html).toContain("原始视频保留在此设备");
    expect(html).toContain("64%");
  });
});
