import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { UploadForm } from "./upload-form";

describe("UploadForm", () => {
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
