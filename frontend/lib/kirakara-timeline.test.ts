import { describe, expect, it } from "vitest";

import {
  activeKirakaraFrame,
  kanjiRuby,
  splitReadingMoras,
  toKirakaraTimeline,
  type CloudAlignedLine,
  type CloudLyricTimeline,
  type KirakaraLine,
  type KirakaraTimeline,
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
  it("uses FA-Kara pronunciation units for sokuon and long vowels", () => {
    expect(splitReadingMoras("きゃっと すーぱー")).toEqual([
      "きゃっ",
      "と",
      "すー",
      "ぱー",
    ]);
  });

  it("isolates ruby to kanji runs inside mixed kana tokens", () => {
    expect(kanjiRuby("お願い", "おねがい")).toEqual([
      { text: "ねが", startCharacter: 1, endCharacter: 2 },
    ]);
  });

  it("starts mixed-token ruby at the matching mora instead of the token start", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("お願い", "おねがい", 1_000, 1_400, [
          {
            surface: "お願い",
            reading: "おねがい",
            start_ms: 1_000,
            end_ms: 1_400,
            confidence: 1,
            moras: [
              { reading: "お", start_ms: 1_000, end_ms: 1_100, matched: true, confidence: 1 },
              { reading: "ね", start_ms: 1_100, end_ms: 1_200, matched: true, confidence: 1 },
              { reading: "が", start_ms: 1_200, end_ms: 1_300, matched: true, confidence: 1 },
              { reading: "い", start_ms: 1_300, end_ms: 1_400, matched: true, confidence: 1 },
            ],
          },
        ]),
      ],
    };

    const beforeRuby = activeKirakaraFrame(toKirakaraTimeline(source), 1_050)
      ?.lines[0].units[0].ruby[0];
    const duringRuby = activeKirakaraFrame(toKirakaraTimeline(source), 1_150)
      ?.lines[0].units[0].ruby[0];

    expect(beforeRuby?.characters).toEqual([
      { text: "ね", progress: 0 },
      { text: "が", progress: 0 },
    ]);
    expect(duringRuby?.characters).toEqual([
      { text: "ね", progress: 0.5 },
      { text: "が", progress: 0 },
    ]);
  });

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

  it("extends each mora to the next mora start only within its lyric line", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("abc", "abc", 1_000, 1_800, [
          {
            surface: "ab",
            reading: "ab",
            start_ms: 1_000,
            end_ms: 1_400,
            confidence: 1,
            moras: [
              { reading: "a", start_ms: 1_000, end_ms: 1_100, matched: true, confidence: 1 },
              { reading: "b", start_ms: 1_300, end_ms: 1_400, matched: true, confidence: 1 },
            ],
          },
          {
            surface: "c",
            reading: "c",
            start_ms: 1_600,
            end_ms: 1_800,
            confidence: 1,
            moras: [
              { reading: "c", start_ms: 1_600, end_ms: 1_800, matched: true, confidence: 1 },
            ],
          },
        ]),
        line("d", "d", 2_200, 2_400, [
          {
            surface: "d",
            reading: "d",
            start_ms: 2_200,
            end_ms: 2_400,
            confidence: 1,
            moras: [
              { reading: "d", start_ms: 2_200, end_ms: 2_400, matched: true, confidence: 1 },
            ],
          },
        ]),
      ],
    };

    const timeline = toKirakaraTimeline(source);

    expect(timeline.lines[0].units[0].moras.map((mora) => [
      mora.startMs,
      mora.endMs,
    ])).toEqual([
      [1_000, 1_300],
      [1_300, 1_600],
    ]);
    expect(timeline.lines[0].units[0].endMs).toBe(1_600);
    expect(timeline.lines[1].units[0].moras[0]).toMatchObject({
      startMs: 2_200,
      endMs: 2_400,
    });
  });

  it("repairs zero-duration source moras before review and export", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("今日", "きょう", 23_429, 23_580, [
          {
            surface: "今日",
            reading: "きょう",
            start_ms: 23_429,
            end_ms: 23_580,
            confidence: 1,
            moras: [
              {
                reading: "きょ",
                start_ms: 23_429,
                end_ms: 23_429,
                matched: false,
                confidence: 0,
              },
              {
                reading: "う",
                start_ms: 23_429,
                end_ms: 23_580,
                matched: true,
                confidence: 1,
              },
            ],
          },
        ]),
      ],
    };

    const moras = toKirakaraTimeline(source).lines[0].units[0].moras;

    expect(moras).toEqual([
      { reading: "きょ", startMs: 23_429, endMs: 23_504, matched: false },
      { reading: "う", startMs: 23_504, endMs: 23_580, matched: true },
    ]);
  });

  it("rebuilds source moras when their count does not match the reading", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("今日", "きょう", 1000, 1400, [
          {
            surface: "今日",
            reading: "きょう",
            start_ms: 1000,
            end_ms: 1400,
            confidence: 1,
            moras: [
              {
                reading: "きょう",
                start_ms: 1000,
                end_ms: 1400,
                matched: false,
                confidence: 0,
              },
            ],
          },
        ]),
      ],
    };

    expect(toKirakaraTimeline(source).lines[0].units[0].moras).toEqual([
      { reading: "きょ", startMs: 1000, endMs: 1200, matched: true },
      { reading: "う", startMs: 1200, endMs: 1400, matched: true },
    ]);
  });

  it("repairs a collapsed line and shifts following lines without overlap", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("君と", "きみと", 1000, 1000, [
          {
            surface: "君",
            reading: "きみ",
            start_ms: 1000,
            end_ms: 1000,
            confidence: 0,
            moras: [],
          },
          {
            surface: "と",
            reading: "と",
            start_ms: 1000,
            end_ms: 1000,
            confidence: 0,
            moras: [],
          },
        ]),
        line("歌う", "うたう", 1000, 1400, [
          {
            surface: "歌う",
            reading: "うたう",
            start_ms: 1000,
            end_ms: 1400,
            confidence: 1,
            moras: [],
          },
        ]),
      ],
    };

    const timeline = toKirakaraTimeline(source);

    expect(timeline.lines[0]).toMatchObject({ startMs: 1000, endMs: 1100 });
    expect(timeline.lines[0].units.map((unit) => [unit.startMs, unit.endMs]))
      .toEqual([[1000, 1067], [1067, 1100]]);
    expect(timeline.lines[1]).toMatchObject({ startMs: 1100, endMs: 1500 });
    expect(timeline.lines[1].units[0]).toMatchObject({
      startMs: 1100,
      endMs: 1500,
    });
    expect(timeline.durationMs).toBe(1500);
  });

  it("allocates time to a collapsed voiced token from its following range", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("火の歌", "ひのうた", 1000, 1600, [
          {
            surface: "火",
            reading: "ひ",
            start_ms: 1000,
            end_ms: 1200,
            confidence: 1,
            moras: [],
          },
          {
            surface: "の",
            reading: "の",
            start_ms: 1200,
            end_ms: 1200,
            confidence: 0,
            moras: [
              { reading: "の", start_ms: 1200, end_ms: 1200, matched: false, confidence: 0 },
            ],
          },
          {
            surface: "歌",
            reading: "うた",
            start_ms: 1200,
            end_ms: 1200,
            confidence: 0,
            moras: [
              { reading: "う", start_ms: 1200, end_ms: 1200, matched: false, confidence: 0 },
              { reading: "た", start_ms: 1200, end_ms: 1200, matched: false, confidence: 0 },
            ],
          },
          {
            surface: "へ",
            reading: "へ",
            start_ms: 1200,
            end_ms: 1600,
            confidence: 1,
            moras: [],
          },
        ]),
      ],
    };

    const units = toKirakaraTimeline(source).lines[0].units;

    expect(units.map((unit) => [unit.startMs, unit.endMs])).toEqual([
      [1000, 1200],
      [1200, 1300],
      [1300, 1500],
      [1500, 1600],
    ]);
    expect(units[2].moras.map((mora) => [mora.startMs, mora.endMs]))
      .toEqual([[1300, 1400], [1400, 1500]]);
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

  it("maps mora timing to one independent progress value per base character", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("東京", "とうきょう", 1000, 1400, [
          {
            surface: "東京",
            reading: "とうきょう",
            start_ms: 1000,
            end_ms: 1400,
            confidence: 1,
            moras: [
              { reading: "とう", start_ms: 1000, end_ms: 1200, matched: true, confidence: 1 },
              { reading: "きょう", start_ms: 1200, end_ms: 1400, matched: true, confidence: 1 },
            ],
          },
        ]),
      ],
    };

    const frame = activeKirakaraFrame(toKirakaraTimeline(source), 1250);
    const unit = frame?.lines[0].units[0] as
      | { characters?: Array<{ text: string; progress: number }> }
      | undefined;

    expect(unit?.characters).toEqual([
      { text: "東", progress: 1 },
      { text: "京", progress: 0.25 },
    ]);
  });

  it("keeps progress moving through a gap until the next mora starts", () => {
    const source: CloudLyricTimeline = {
      confidence: 1,
      warnings: [],
      lines: [
        line("火", "ab", 1_000, 1_600, [
          {
            surface: "火",
            reading: "ab",
            start_ms: 1_000,
            end_ms: 1_600,
            confidence: 1,
            moras: [
              { reading: "a", start_ms: 1_000, end_ms: 1_200, matched: true, confidence: 1 },
              { reading: "b", start_ms: 1_400, end_ms: 1_600, matched: true, confidence: 1 },
            ],
          },
        ]),
      ],
    };

    const unit = activeKirakaraFrame(toKirakaraTimeline(source), 1_300)
      ?.lines[0].units[0];
    expect(unit?.progress).toBeCloseTo(0.375);
    expect(unit?.ruby[0]).toMatchObject({
      characters: [
        { text: "a", progress: 0.75 },
        { text: "b", progress: 0 },
      ],
    });
  });

  it("uses Kirakara paragraph timing and resets the first pair to upper and lower", () => {
    const lyric = (text: string, startMs: number, endMs: number): KirakaraLine => ({
      text,
      reading: text,
      startMs,
      endMs,
      units: [{ text, reading: text, startMs, endMs, moras: [], ruby: [] }],
    });
    const timeline: KirakaraTimeline = {
      confidence: 1,
      warnings: [],
      durationMs: 11_500,
      lines: [
        lyric("line-1", 1_000, 1_500),
        lyric("line-2", 2_000, 2_500),
        lyric("line-3", 3_000, 3_500),
        lyric("line-4", 10_000, 10_500),
        lyric("line-5", 11_000, 11_500),
      ],
    };

    expect(activeKirakaraFrame(timeline, 6_000)?.lines).toEqual([
      expect.objectContaining({ slot: "upper", text: "line-4" }),
      expect.objectContaining({ slot: "lower", text: "line-5" }),
    ]);

    const entryFrame = activeKirakaraFrame(timeline, 5_834);
    expect(entryFrame?.lines).toEqual([
      expect.objectContaining({
        slot: "upper",
        text: "line-4",
        opacity: 0,
        indicatorOpacities: [1, 1, 1, 1],
      }),
      expect.objectContaining({ slot: "lower", text: "line-5", opacity: 0 }),
    ]);
  });
});
