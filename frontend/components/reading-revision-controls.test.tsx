import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReadingRevisionControls } from "./reading-revision-controls";

describe("ReadingRevisionControls", () => {
  it("offers a previous step for changing the last reviewed kana", () => {
    const html = renderToStaticMarkup(
      <ReadingRevisionControls reopening={false} onReopen={vi.fn()} />,
    );

    expect(html).toContain("上一步：修改假名注音");
    expect(html).toContain("以上次保存的注音为基础");
  });
});
