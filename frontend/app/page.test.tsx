import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import Home from "./page";

describe("Cloud home page", () => {
  it("shows the author and open-source contact information", () => {
    const html = renderToStaticMarkup(<Home />);

    expect(html).toContain("qq：280475274");
    expect(html).toContain("bilibili：esrgt");
    expect(html).toContain("小红书：esr");
    expect(html).toContain(
      "项目已开源，欢迎关注项目更新进度，与错误反馈或修改建议",
    );
  });
});
