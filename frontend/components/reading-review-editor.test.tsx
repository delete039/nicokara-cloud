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

  it("does not require a reading for whitespace lyric tokens", () => {
    const html = renderToStaticMarkup(
      <ReadingReviewEditor
        lyrics={{
          provider: "local",
          source_text: "君 は",
          warnings: [],
          lines: [
            {
              source: "君 は",
              surface: "君 は",
              reading: "きみ は",
              tokens: [
                { surface: "君", reading: "きみ" },
                { surface: " ", reading: " " },
                { surface: "は", reading: "は" },
              ],
            },
          ],
        }}
        submitting={false}
        onChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(html.match(/<input/g)).toHaveLength(2);
    expect(html).toContain('aria-label="空格，无需注音"');
    expect(html).not.toContain('<button type="button" disabled=""');
  });

  it("still blocks confirmation when a non-whitespace reading is empty", () => {
    const html = renderToStaticMarkup(
      <ReadingReviewEditor
        lyrics={{
          provider: "local",
          source_text: "君",
          warnings: [],
          lines: [
            {
              source: "君",
              surface: "君",
              reading: "",
              tokens: [{ surface: "君", reading: "" }],
            },
          ],
        }}
        submitting={false}
        onChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(html).toContain('<button type="button" disabled=""');
  });
});
