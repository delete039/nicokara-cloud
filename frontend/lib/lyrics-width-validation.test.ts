import { describe, expect, it } from "vitest";

import {
  KIRAKARA_FULLWIDTH_CHARACTER_LIMIT,
  detectLyricsWidthOverflow,
  extractVisibleLyricLines,
  readLyricsValidationSource,
} from "./lyrics-width-validation";

const measureFullwidth = () => 48;

describe("lyrics width validation", () => {
  it("allows 20 fullwidth characters and warns at 21 with the Kirakara minimum font size", () => {
    expect(KIRAKARA_FULLWIDTH_CHARACTER_LIMIT).toBe(20);
    expect(
      detectLyricsWidthOverflow("あ".repeat(20), {
        measureCharacter: measureFullwidth,
      }),
    ).toBeNull();

    const report = detectLyricsWidthOverflow("あ".repeat(21), {
      measureCharacter: measureFullwidth,
    });

    expect(report).not.toBeNull();
    expect(report?.lines[0]).toMatchObject({
      lineNumber: 1,
      characterCount: 21,
      widthPx: 1188,
    });
  });

  it("uses rendered width instead of rejecting every line over 20 characters", () => {
    const report = detectLyricsWidthOverflow("abcdefghijklmnopqrstu", {
      measureCharacter: () => 24,
    });

    expect(report).toBeNull();
  });

  it("warns when likely kanji ruby makes a 20-character line exceed the canvas", () => {
    const report = detectLyricsWidthOverflow(
      "不均衡　パラって　後はどうにかしてよね，",
      { measureCharacter: measureFullwidth },
    );

    expect(report).not.toBeNull();
    expect(report?.lines[0]).toMatchObject({
      lineNumber: 1,
      characterCount: 20,
      widthPx: 1167,
    });
  });

  it("extracts visible lyrics from LRC metadata, timestamps, and Kirakara ruby annotations", () => {
    const lines = extractVisibleLyricLines(
      [
        "[ti:Song title]",
        "[00:01.20][00:03.00]{漢字|かんじ}" + "あ".repeat(19),
        "",
        "plain text",
      ].join("\n"),
    );

    expect(lines).toEqual([
      { lineNumber: 2, text: "漢字" + "あ".repeat(19) },
      { lineNumber: 4, text: "plain text" },
    ]);

    const report = detectLyricsWidthOverflow(
      "[ti:Song title]\n[00:01.20]{漢字|かんじ}" + "あ".repeat(19),
      { measureCharacter: measureFullwidth },
    );
    expect(report?.lines[0].lineNumber).toBe(2);
    expect(report?.lines[0].text).toBe("漢字" + "あ".repeat(19));
  });

  it("reads pasted lyrics and TXT/LRC files through the same source contract", async () => {
    await expect(readLyricsValidationSource("pasted lyrics", null)).resolves.toEqual({
      label: "粘贴的歌词",
      text: "pasted lyrics",
      signature: "text\u0000pasted lyrics",
    });

    const file = {
      name: "lyrics.lrc",
      text: async () => "[00:01.00]file lyrics",
    };
    await expect(readLyricsValidationSource("", file)).resolves.toEqual({
      label: "lyrics.lrc",
      text: "[00:01.00]file lyrics",
      signature: "file:lyrics.lrc\u0000[00:01.00]file lyrics",
    });
  });
});
