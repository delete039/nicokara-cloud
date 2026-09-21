import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { UploadForm } from "./upload-form";

describe("UploadForm", () => {
  it("uses one submission entry instead of choosing the vocal mode at upload", () => {
    const html = renderToStaticMarkup(<UploadForm />);
    expect(html).not.toContain('id="vocal-heading"');
    expect(html).toContain("生成后可分别导出 ON VOCAL 和 OFF VOCAL");
  });
  it("does not expose alignment model choices on the main upload page", () => {
    const html = renderToStaticMarkup(<UploadForm />);

    expect(html).not.toContain("时间轴模式");
    expect(html).not.toContain("多声部增强");
    expect(html).not.toContain("稳健双模型");
  });
  it("shows that MP4 videos can be dragged onto the upload area", () => {
    const html = renderToStaticMarkup(<UploadForm />);

    expect(html).toContain("拖放 MP4 文件到这里");
  });

  it("accepts existing LRC lyric files as well as plain text", () => {
    const html = renderToStaticMarkup(<UploadForm />);

    expect(html).toContain('accept=".txt,.lrc,text/plain,application/x-subrip"');
    expect(html).toContain("选择 TXT / LRC 文件");
  });
});
