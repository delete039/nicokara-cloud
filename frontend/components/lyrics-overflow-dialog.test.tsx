import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { LyricsOverflowDialog } from "./lyrics-overflow-dialog";

describe("LyricsOverflowDialog", () => {
  it("explains the Kirakara limit and offers a safe return or explicit override", () => {
    const html = renderToStaticMarkup(
      <LyricsOverflowDialog
        report={{
          availableWidthPx: 1152,
          fullwidthCharacterLimit: 20,
          totalOverflowingLines: 1,
          lines: [
            {
              lineNumber: 3,
              text: "あ".repeat(21),
              excerpt: "あ".repeat(21),
              characterCount: 21,
              widthPx: 1188,
            },
          ],
        }}
        sourceLabel="lyrics.lrc"
        onCancel={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(html).toContain("歌词单行可能超出字幕画面");
    expect(html).toContain("确认要继续吗？");
    expect(html).toContain("Kirakara 最小字号 48 px");
    expect(html).toContain("约 20 个全角字符");
    expect(html).toContain("汉字注音较宽时会进一步占用空间");
    expect(html).toContain("第 3 行");
    expect(html).toContain("返回修改");
    expect(html).toContain("忽略风险并继续");
  });
});
