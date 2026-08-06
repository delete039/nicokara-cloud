import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

async function loadRouteStatus() {
  const modulePath = "./mobile-route-status";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("MobileRouteStatus", () => {
  it("names the selected audio-only path and the 300 MB local boundary", async () => {
    const routeStatus = await loadRouteStatus();
    expect(routeStatus, "mobile route status component should exist").not.toBeNull();
    if (!routeStatus) return;

    const html = renderToStaticMarkup(
      <routeStatus.MobileRouteStatus route="AUDIO_ONLY" />,
    );

    expect(html).toContain("仅上传音频");
    expect(html).toContain("300 MB");
    expect(html).not.toContain("模型推理已完成");
  });

  it("keeps the remote fallback wording transport-neutral", async () => {
    const routeStatus = await loadRouteStatus();
    expect(routeStatus).not.toBeNull();
    if (!routeStatus) return;

    const html = renderToStaticMarkup(
      <routeStatus.MobileRouteStatus route="REMOTE_VIDEO" />,
    );
    expect(html).toContain("完整视频上传");
    expect(html).not.toContain("已上传 OSS");
    expect(html).not.toContain("移动端");
  });
});
