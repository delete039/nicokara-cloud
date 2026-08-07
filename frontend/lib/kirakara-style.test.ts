import { describe, expect, it } from "vitest";

import {
  DEFAULT_KIRAKARA_STYLE,
  loadKirakaraStyle,
  normalizeKirakaraStyle,
} from "./kirakara-style";

describe("Kirakara style", () => {
  it("uses the Kirakara 1280 x 720 layout defaults", () => {
    expect(DEFAULT_KIRAKARA_STYLE).toMatchObject({
      fontSize: 64,
      rubySize: 26,
      upperY: 430,
      lowerY: 563,
      colorBefore: "#ffffff",
      colorAfter: "#a50000",
    });
  });

  it("clamps persisted values and falls back from invalid colors", () => {
    expect(
      normalizeKirakaraStyle({
        fontSize: 500,
        rubySize: 1,
        upperY: 999,
        colorAfter: "red",
      }),
    ).toMatchObject({
      fontSize: 80,
      rubySize: 18,
      upperY: 560,
      colorAfter: DEFAULT_KIRAKARA_STYLE.colorAfter,
    });
  });

  it("loads a saved style without trusting malformed storage", () => {
    const storage = {
      getItem: () => JSON.stringify({ fontSize: 72, strokeWidth: 6 }),
    };

    expect(loadKirakaraStyle(storage)).toMatchObject({
      fontSize: 72,
      strokeWidth: 6,
    });
    expect(loadKirakaraStyle({ getItem: () => "{" })).toEqual(
      DEFAULT_KIRAKARA_STYLE,
    );
  });

  it("preserves a user-entered system font stack like upstream Kirakara", () => {
    expect(
      normalizeKirakaraStyle({
        fontFamily: "'Hiragino Sans', sans-serif",
      }).fontFamily,
    ).toBe("'Hiragino Sans', sans-serif");
  });

  it("rejects control characters in custom font names", () => {
    expect(
      normalizeKirakaraStyle({ fontFamily: "Broken\nFont" }).fontFamily,
    ).toBe(DEFAULT_KIRAKARA_STYLE.fontFamily);
  });
});
