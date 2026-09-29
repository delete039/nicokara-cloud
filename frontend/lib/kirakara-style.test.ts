import { describe, expect, it } from "vitest";

import {
  DEFAULT_KIRAKARA_STYLE,
  KIRAKARA_STYLE_PRESETS,
  kirakaraStylePayload,
  loadKirakaraStyle,
  normalizeKirakaraStyle,
} from "./kirakara-style";

describe("Kirakara style", () => {
  it("REQ-STYLE-DEFAULT-01 uses the Kirakara 1280 x 720 layout defaults", () => {
    expect(DEFAULT_KIRAKARA_STYLE).toMatchObject({
      fontSize: 64,
      fontBold: true,
      letterSpacing: 9,
      rubySize: 26,
      rubyLetterSpacing: 5,
      rubyOffset: 4,
      romajiFollowRuby: true,
      romajiSize: 26,
      romajiLetterSpacing: 5,
      romajiOffset: 4,
      strokeColorBefore: "#000000",
      strokeColorAfter: "#ffffff",
      shadowDepth: 0,
      horizontalMargin: 128,
      upperY: 430,
      lowerY: 563,
      colorBefore: "#ffffff",
      colorAfter: "#a50000",
    });
  });

  it("REQ-STYLE-RANGE-01 widens useful ranges and clamps unsafe extremes", () => {
    expect(
      normalizeKirakaraStyle({
        fontSize: 500,
        rubySize: 1,
        letterSpacing: -20,
        rubyOffset: 80,
        strokeWidth: -1,
        horizontalMargin: 999,
        upperY: 999,
        colorAfter: "red",
      }),
    ).toMatchObject({
      fontSize: 120,
      rubySize: 10,
      letterSpacing: -4,
      rubyOffset: 32,
      strokeWidth: 0,
      horizontalMargin: 320,
      upperY: 600,
      colorAfter: DEFAULT_KIRAKARA_STYLE.colorAfter,
    });
  });

  it("REQ-STYLE-RANGE-02 accepts a main font smaller than the old 48px minimum", () => {
    expect(normalizeKirakaraStyle({ fontSize: 32 }).fontSize).toBe(32);
  });

  it("keeps romaji linked to kana by default and normalizes independent preview values", () => {
    expect(normalizeKirakaraStyle({
      rubySize: 31,
      rubyLetterSpacing: 7,
      rubyOffset: 9,
    })).toMatchObject({
      romajiFollowRuby: true,
      romajiSize: 31,
      romajiLetterSpacing: 7,
      romajiOffset: 9,
    });
    expect(normalizeKirakaraStyle({
      romajiFollowRuby: false,
      romajiSize: 500,
      romajiLetterSpacing: -20,
      romajiOffset: 80,
    })).toMatchObject({
      romajiFollowRuby: false,
      romajiSize: 60,
      romajiLetterSpacing: -2,
      romajiOffset: 32,
    });
  });

  it("REQ-STYLE-PRESET-01 provides complete normalized style presets", () => {
    expect(KIRAKARA_STYLE_PRESETS.map(({ id }) => id)).toEqual([
      "classic",
      "compact",
      "soft-shadow",
    ]);
    expect(KIRAKARA_STYLE_PRESETS.every(
      ({ style }) => normalizeKirakaraStyle(style).fontSize === style.fontSize,
    )).toBe(true);
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

  it("sends the first CSS font family without CSS quotes", () => {
    expect(
      kirakaraStylePayload({
        ...DEFAULT_KIRAKARA_STYLE,
        fontFamily: "'Yu Mincho', serif",
      }).font_family,
    ).toBe("Yu Mincho");
  });

  it("REQ-STYLE-PAYLOAD-01 sends every render-affecting style field", () => {
    const payload = kirakaraStylePayload({
      ...DEFAULT_KIRAKARA_STYLE,
      fontBold: false,
      letterSpacing: 3,
      rubyLetterSpacing: 2,
      rubyOffset: 8,
      strokeColorBefore: "#112233",
      strokeColorAfter: "#aabbcc",
      shadowColor: "#445566",
      shadowDepth: 4,
      horizontalMargin: 96,
      romajiFollowRuby: false,
      romajiSize: 45,
      romajiLetterSpacing: 8,
      romajiOffset: 12,
    });
    expect(payload).toMatchObject({
      font_bold: false,
      letter_spacing: 3,
      ruby_letter_spacing: 2,
      ruby_offset: 8,
      stroke_color_before: "#112233",
      stroke_color_after: "#aabbcc",
      shadow_color: "#445566",
      shadow_depth: 4,
      horizontal_margin: 96,
      romaji_follow_ruby: false,
      romaji_size: 45,
      romaji_letter_spacing: 8,
      romaji_offset: 12,
    });
  });
});
