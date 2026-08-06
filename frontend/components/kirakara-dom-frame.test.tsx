import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";
import type { KirakaraFrame } from "@/lib/kirakara-timeline";

async function loadDomFrame() {
  const modulePath = "./kirakara-dom-frame";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("KirakaraDomFrame", () => {
  it("renders one clipped DOM mask for each independently timed character", async () => {
    const renderer = await loadDomFrame();
    expect(renderer, "Kirakara DOM renderer should exist").not.toBeNull();
    if (!renderer) return;

    const frame = {
      lines: [
        {
          slot: "upper" as const,
          text: "東京",
          units: [
            {
              text: "東京",
              progress: 0.625,
              characters: [
                { text: "東", progress: 1 },
                { text: "京", progress: 0.25 },
              ],
              ruby: [{ text: "とうきょう", startCharacter: 0, endCharacter: 2 }],
            },
          ],
        },
      ],
    } as unknown as KirakaraFrame;

    const html = renderToStaticMarkup(
      <renderer.KirakaraDomFrame
        frame={frame}
        style={DEFAULT_KIRAKARA_STYLE}
      />,
    );

    expect(html).toContain('data-kirakara-dom-preview="true"');
    expect(html.match(/data-kirakara-character=/g)).toHaveLength(2);
    expect(html).toContain("clip-path:inset(-50% calc(75% + 0.5px) -50% -5px)");
    expect(html).toContain('data-kirakara-ruby-sizer="true"');
    expect(html).not.toContain("letter-spacing:5px");
  });
});
