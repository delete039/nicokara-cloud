import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { KirakaraStyleEditor } from "./kirakara-style-editor";
import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";

describe("KirakaraStyleEditor", () => {
  it("exposes a compact set of Kirakara style controls", () => {
    const html = renderToStaticMarkup(
      <KirakaraStyleEditor
        style={DEFAULT_KIRAKARA_STYLE}
        onChange={vi.fn()}
      />,
    );

    expect(html).toContain("字幕样式");
    expect(html).toContain("字体");
    expect(html).toContain("主字大小");
    expect(html).toContain("注音大小");
    expect(html).toContain("未唱颜色");
    expect(html).toContain("已唱颜色");
    expect(html).toContain("上行位置");
    expect(html).toContain("下行位置");
    expect(html).toContain("恢复 Kirakara 默认样式");
  });
});
