import { describe, expect, it } from "vitest";

import {
  activeKirakaraFrame,
  toKirakaraTimeline,
  type CloudAlignedLine,
  type CloudLyricTimeline,
} from "./kirakara-timeline";

function line(
  surface: string,
  reading: string,
  startMs: number,
  endMs: number,
  tokens: CloudAlignedLine["tokens"],
): CloudAlignedLine {
  return {
    surface,
    reading,
    start_ms: startMs,
    end_ms: endMs,
    confidence: 1,
    tokens,
  };
}

const cloudTimeline: CloudLyricTimeline = {
  confidence: 0.94,
  warnings: [],
  lines: [
    line("今日も", "きょうも", 1000, 1600, [
      {
        surface: "今日",
        reading: "きょう",
        start_ms: 1000,
        end_ms: 1400,
        confidence: 1,
        moras: [
          { reading: "きょ", start_ms: 1000, end_ms: 1200, matched: true, confidence: 1 },
          { reading: "う", start_ms: 1200, end_ms: 1400, matched: true, confidence: 1 },
        ],
      },
      {
        surface: "も",
        reading: "も",
        start_ms: 1400,
        end_ms: 1600,
        confidence: 1,
        moras: [],
      },
    ]),
    line("歌う", "うたう", 2000, 2600, [
      {
        surface: "歌",
        reading: "うた",
        start_ms: 2000,
        end_ms: 2400,
        confidence: 1,
        moras: [],
      },
      {
        surface: "う",
        reading: "う",
        start_ms: 2400,
        end_ms: 2600,
        confidence: 1,
        moras: [],
      },
    ]),
    line("明日へ", "あしたへ", 3000, 3600, [
      {
        surface: "明日",
        reading: "あした",
        start_ms: 3000,
        end_ms: 3400,
        confidence: 1,
        moras: [],
      },
      {
        surface: "へ",
        reading: "へ",
        start_ms: 3400,
        end_ms: 3600,
        confidence: 1,
        moras: [],
      },
    ]),
  ],
};

describe("toKirakaraTimeline", () => {
  it("keeps mora timing and creates ruby only for kanji groups", () => {
    const timeline = toKirakaraTimeline(cloudTimeline);

    expect(timeline.durationMs).toBe(3600);
    expect(timeline.lines[0].units[0].moras.map((mora) => mora.reading)).toEqual([
      "きょ",
      "う",
    ]);
    expect(timeline.lines[0].units[0].ruby).toEqual([
      { text: "きょう", startCharacter: 0, endCharacter: 2 },
    ]);
    expect(timeline.lines[0].units[1].ruby).toEqual([]);
  });
});

describe("activeKirakaraFrame", () => {
  it("shows the current and next lyric in alternating upper and lower slots", () => {
    const frame = activeKirakaraFrame(toKirakaraTimeline(cloudTimeline), 1250);

    expect(frame?.lines).toHaveLength(2);
    expect(frame?.lines).toEqual([
      expect.objectContaining({ slot: "upper", text: "今日も" }),
      expect.objectContaining({ slot: "lower", text: "歌う" }),
    ]);
  });

  it("replaces a completed slot with the following lyric", () => {
    const frame = activeKirakaraFrame(toKirakaraTimeline(cloudTimeline), 2100);

    expect(frame?.lines).toEqual([
      expect.objectContaining({ slot: "upper", text: "明日へ" }),
      expect.objectContaining({ slot: "lower", text: "歌う" }),
    ]);
  });

  it("uses mora timing for progress inside a kanji token", () => {
    const frame = activeKirakaraFrame(toKirakaraTimeline(cloudTimeline), 1250);
    const upper = frame?.lines.find((candidate) => candidate.slot === "upper");

    expect(upper?.units[0].progress).toBeCloseTo(0.625);
    expect(upper?.units[1].progress).toBe(0);
  });
});
