import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReadingReviewEditor } from "./reading-review-editor";

describe("ReadingReviewEditor", () => {
  it("edits token readings before FA-Kara creates mora timing", () => {
    const html = renderToStaticMarkup(
      <ReadingReviewEditor
        lyrics={{
          provider: "local",
          source_text: "君は",
          warnings: [],
          lines: [
            {
              source: "君は",
              surface: "君は",
              reading: "くんは",
              tokens: [
                { surface: "君", reading: "くん" },
                { surface: "は", reading: "は", alignment_pronunciation: "wa" },
              ],
            },
          ],
        }}
        submitting={false}
        onChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(html).toContain("确认假名注音");
    expect(html).toContain("君は");
    expect(html).toContain('value="くん"');
    expect(html).toContain('value="は"');
    expect(html).toContain("保存注音并开始对齐");
    expect(html).not.toContain("设置时间轴");
  });
});
