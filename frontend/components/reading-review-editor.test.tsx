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
    expect(html).toContain("修改会自动保存在此浏览器");
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

  it("warns when a foreign word still has an unconverted reading", () => {
    const html = renderToStaticMarkup(
      <ReadingReviewEditor
        lyrics={{
          provider: "local",
          source_text: "LOVEを歌う",
          warnings: [],
          lines: [
            {
              source: "LOVEを歌う",
              surface: "LOVEを歌う",
              reading: "LOVEをうたう",
              tokens: [
                { surface: "LOVE", reading: "LOVE" },
                { surface: "を", reading: "を" },
                { surface: "歌", reading: "うた" },
                { surface: "う", reading: "う" },
              ],
            },
          ],
        }}
        submitting={false}
        onChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("请确认将外来语注音为假名");
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain("LOVE → らぶ");
  });

  it("asks for confirmation when a foreign word has generated kana", () => {
    const html = renderToStaticMarkup(
      <ReadingReviewEditor
        lyrics={{
          provider: "local",
          source_text: "LOVEを歌う",
          warnings: ["local_reading_may_be_inaccurate"],
          lines: [
            {
              source: "LOVEを歌う",
              surface: "LOVEを歌う",
              reading: "らぶをうたう",
              tokens: [
                { surface: "LOVE", reading: "らぶ" },
                { surface: "を", reading: "を" },
                { surface: "歌", reading: "うた" },
                { surface: "う", reading: "う" },
              ],
            },
          ],
        }}
        submitting={false}
        onChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(html).toContain("请确认将外来语注音为假名");
    expect(html).toContain("系统已提供默认读音");
  });

  it("allows confirmation when a generated reading is left empty", () => {
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

    expect(html).toContain("留空将沿用系统生成的读音");
    expect(html).not.toContain('<button type="button" disabled=""');
  });
});
