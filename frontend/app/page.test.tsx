import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import Home from "./page";

describe("Cloud home page", () => {
  it("shows the intro content and centers the upload form column", () => {
    const html = renderToStaticMarkup(<Home />);

    expect(html).toContain("qq：280475274");
    expect(html).toContain("bilibili：esrgt");
    expect(html).toContain("小红书：esr");
    expect(html).toContain('href="https://github.com/delete039/nicokara-cloud"');
    expect(html).toContain('href="https://github.com/FMPeach"');
    expect(html).toContain('href="https://github.com/FMPeach/Kirakara-Player"');
    expect(html).toContain('href="https://github.com/moriwx"');
    expect(html).toContain('href="https://github.com/moriwx/FA-Kara"');
    expect(html).toContain("特别鸣谢");
    expect(html).toContain("打开公告");
    expect(html).toContain('id="upload-form"');
    expect(html).toContain("lg:min-h-[calc(100dvh-5rem)]");
    expect(html).toContain("视频素材");
    expect(html).not.toContain("LOCAL");
  });

  it("places the announcement action inside the author information area", () => {
    const html = renderToStaticMarkup(<Home />);

    expect(html).toMatch(
      /<aside[^>]*aria-label="作者信息"[^>]*>[\s\S]*打开公告[\s\S]*<\/aside>/,
    );
  });
});
