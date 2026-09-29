import { describe, expect, it } from "vitest";

import { romanizeReadingMoras } from "./japanese-romaji";

describe("Japanese romaji export", () => {
  it("keeps digraphs as one display mora", () => {
    expect(romanizeReadingMoras(["びょ", "う"])).toEqual(["byo", "u"]);
    expect(romanizeReadingMoras(["しょ"])).toEqual(["sho"]);
  });

  it("maps sokuon to the following consonant", () => {
    expect(romanizeReadingMoras(["っ", "て"])).toEqual(["t", "te"]);
    expect(romanizeReadingMoras(["っ", "ちゃ"])).toEqual(["c", "cha"]);
    expect(romanizeReadingMoras(["らっ", "だ"])).toEqual(["rad", "da"]);
  });

  it("uses the display spelling for long vowels and particles", () => {
    expect(romanizeReadingMoras(["たー"])).toEqual(["ta-"]);
    expect(romanizeReadingMoras(["は"], "は")).toEqual(["wa"]);
    expect(romanizeReadingMoras(["へ"], "へ")).toEqual(["e"]);
    expect(romanizeReadingMoras(["を"], "を")).toEqual(["o"]);
    expect(romanizeReadingMoras(["ん", "あ"])).toEqual(["n'", "a"]);
  });
});
