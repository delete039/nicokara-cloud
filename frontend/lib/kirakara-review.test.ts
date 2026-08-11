import { describe, expect, it } from "vitest";

import type { KirakaraTimeline } from "./kirakara-timeline";
import {
  applyLineEdgeOffset,
  applyLineOffset,
  applyTimelineOffset,
  timelineDragOffsetMs,
  timelineReviewPayload,
  updateLineRange,
  updateMoraBoundary,
  updateUnitReading,
} from "./kirakara-review";
import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";

const timeline: KirakaraTimeline = {
  confidence: 0.9,
  warnings: [],
  durationMs: 3000,
  lines: [
    {
      text: "君の",
      reading: "きみの",
      startMs: 1000,
      endMs: 3000,
      units: [
        {
          text: "君",
          reading: "きみ",
          startMs: 1000,
          endMs: 2000,
          moras: [
            { reading: "き", startMs: 1000, endMs: 1500, matched: true },
            { reading: "み", startMs: 1500, endMs: 2000, matched: true },
          ],
        },
        {
          text: "の",
          reading: "の",
          startMs: 2000,
          endMs: 3000,
          moras: [],
        },
      ],
    },
  ],
};

describe("Kirakara timeline review", () => {
  it("converts a horizontal timeline drag to a millisecond offset", () => {
    expect(timelineDragOffsetMs(75, 600, 4000)).toBe(500);
    expect(timelineDragOffsetMs(-150, 600, 4000)).toBe(-1000);
    expect(timelineDragOffsetMs(100, 0, 4000)).toBe(0);
  });

  it("moves one line with every token and mora by the same offset", () => {
    const updated = applyLineOffset(timeline, 0, 750);

    expect(updated.lines[0]).toMatchObject({ startMs: 1750, endMs: 3750 });
    expect(updated.lines[0].units[0]).toMatchObject({
      startMs: 1750,
      endMs: 2750,
    });
    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "き", startMs: 1750, endMs: 2250, matched: true },
      { reading: "み", startMs: 2250, endMs: 2750, matched: true },
    ]);
    expect(updated.lines[0].units[1]).toMatchObject({
      startMs: 2750,
      endMs: 3750,
    });
    expect(updated.durationMs).toBe(3750);
  });

  it("resizes a line start and proportionally adapts every token and mora", () => {
    const updated = applyLineEdgeOffset(timeline, 0, "start", 500);

    expect(updated.lines[0]).toMatchObject({ startMs: 1500, endMs: 3000 });
    expect(updated.lines[0].units[0]).toMatchObject({
      startMs: 1500,
      endMs: 2250,
    });
    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "き", startMs: 1500, endMs: 1875, matched: true },
      { reading: "み", startMs: 1875, endMs: 2250, matched: true },
    ]);
    expect(updated.lines[0].units[1]).toMatchObject({
      startMs: 2250,
      endMs: 3000,
    });
  });

  it("resizes a line end and proportionally adapts every token and mora", () => {
    const updated = applyLineEdgeOffset(timeline, 0, "end", 2000);

    expect(updated.lines[0]).toMatchObject({ startMs: 1000, endMs: 5000 });
    expect(updated.lines[0].units[0]).toMatchObject({
      startMs: 1000,
      endMs: 3000,
    });
    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "き", startMs: 1000, endMs: 2000, matched: true },
      { reading: "み", startMs: 2000, endMs: 3000, matched: true },
    ]);
    expect(updated.lines[0].units[1]).toMatchObject({
      startMs: 3000,
      endMs: 5000,
    });
    expect(updated.durationMs).toBe(5000);
  });

  it("keeps a dragged line between its neighboring lines", () => {
    const withNeighbors: KirakaraTimeline = {
      ...timeline,
      durationMs: 4500,
      lines: [
        {
          text: "前",
          reading: "まえ",
          startMs: 0,
          endMs: 800,
          units: [
            { text: "前", reading: "まえ", startMs: 0, endMs: 800, moras: [] },
          ],
        },
        timeline.lines[0],
        {
          text: "後",
          reading: "あと",
          startMs: 3500,
          endMs: 4500,
          units: [
            { text: "後", reading: "あと", startMs: 3500, endMs: 4500, moras: [] },
          ],
        },
      ],
    };

    const movedRight = applyLineOffset(withNeighbors, 1, 1000);
    expect(movedRight.lines[1]).toMatchObject({ startMs: 1500, endMs: 3500 });
    expect(movedRight.lines[1].units[0].moras[0]).toMatchObject({
      startMs: 1500,
      endMs: 2000,
    });

    const movedLeft = applyLineOffset(withNeighbors, 1, -1000);
    expect(movedLeft.lines[1]).toMatchObject({ startMs: 800, endMs: 2800 });
    expect(movedLeft.lines[1].units[0]).toMatchObject({
      startMs: 800,
      endMs: 1800,
    });

    const resizedStart = applyLineEdgeOffset(withNeighbors, 1, "start", -1000);
    expect(resizedStart.lines[1]).toMatchObject({ startMs: 800, endMs: 3000 });
    expect(resizedStart.lines[1].units[0]).toMatchObject({
      startMs: 800,
      endMs: 1900,
    });

    const resizedEnd = applyLineEdgeOffset(withNeighbors, 1, "end", 1000);
    expect(resizedEnd.lines[1]).toMatchObject({ startMs: 1000, endMs: 3500 });
    expect(resizedEnd.lines[1].units[0]).toMatchObject({
      startMs: 1000,
      endMs: 2250,
    });
  });

  it("clamps a negative line move without collapsing token durations", () => {
    const updated = applyLineOffset(timeline, 0, -1500);

    expect(updated.lines[0]).toMatchObject({ startMs: 0, endMs: 2000 });
    expect(updated.lines[0].units[0]).toMatchObject({ startMs: 0, endMs: 1000 });
    expect(updated.lines[0].units[0].moras[1]).toMatchObject({
      startMs: 500,
      endMs: 1000,
    });
  });

  it("rescales token and mora timing when a line range changes", () => {
    const updated = updateLineRange(timeline, 0, 2000, 6000);

    expect(updated.lines[0]).toMatchObject({ startMs: 2000, endMs: 6000 });
    expect(updated.lines[0].units[0]).toMatchObject({ startMs: 2000, endMs: 4000 });
    expect(updated.lines[0].units[0].moras[0]).toMatchObject({
      startMs: 2000,
      endMs: 3000,
    });
    expect(updated.durationMs).toBe(6000);
  });

  it("redistributes collapsed token and mora timing when a zero-length line is repaired", () => {
    const collapsed: KirakaraTimeline = {
      confidence: 0,
      warnings: ["partial_alignment"],
      durationMs: 25050,
      lines: [{
        text: "僕ら、",
        reading: "ぼくら、",
        startMs: 25050,
        endMs: 25050,
        units: [
          {
            text: "僕ら",
            reading: "ぼくら",
            startMs: 25050,
            endMs: 25050,
            moras: [
              { reading: "ぼく", startMs: 25050, endMs: 25050, matched: false },
              { reading: "ら", startMs: 25050, endMs: 25050, matched: false },
            ],
          },
          {
            text: "は",
            reading: "は",
            startMs: 25050,
            endMs: 25050,
            moras: [
              { reading: "は", startMs: 25050, endMs: 25050, matched: false },
            ],
          },
          {
            text: "、",
            reading: "、",
            startMs: 25050,
            endMs: 25050,
            moras: [],
          },
        ],
      }],
    };

    const updated = updateLineRange(collapsed, 0, 20000, 23000);

    expect(updated.lines[0]).toMatchObject({ startMs: 20000, endMs: 23000 });
    expect(updated.lines[0].units[0]).toMatchObject({ startMs: 20000, endMs: 22000 });
    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "ぼく", startMs: 20000, endMs: 21000, matched: false },
      { reading: "ら", startMs: 21000, endMs: 22000, matched: false },
    ]);
    expect(updated.lines[0].units[1]).toMatchObject({ startMs: 22000, endMs: 23000 });
    expect(updated.lines[0].units[1].moras[0]).toMatchObject({
      startMs: 22000,
      endMs: 23000,
    });
    expect(updated.lines[0].units[2]).toMatchObject({ startMs: 23000, endMs: 23000 });

    const adjusted = updateMoraBoundary(updated, 0, 0, 20500);
    expect(adjusted.lines[0].units[0].moras[0]).toMatchObject({ endMs: 20500 });
    expect(adjusted.lines[0].units[0].moras[1]).toMatchObject({ startMs: 20500 });
  });

  it("moves one boundary shared by two moras", () => {
    const updated = updateMoraBoundary(timeline, 0, 0, 1750);

    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "き", startMs: 1000, endMs: 1750, matched: true },
      { reading: "み", startMs: 1750, endMs: 2000, matched: true },
    ]);
    expect(updated.lines[0]).toMatchObject({ startMs: 1000, endMs: 3000 });
  });

  it("moves a mora boundary across token and punctuation units", () => {
    const source: KirakaraTimeline = {
      ...timeline,
      lines: [{
        ...timeline.lines[0],
        text: "君、の",
        units: [
          timeline.lines[0].units[0],
          { text: "、", reading: "、", startMs: 2000, endMs: 2000, moras: [] },
          {
            text: "の",
            reading: "の",
            startMs: 2200,
            endMs: 3000,
            moras: [
              { reading: "の", startMs: 2200, endMs: 3000, matched: true },
            ],
          },
        ],
      }],
    };

    const updated = updateMoraBoundary(source, 0, 1, 2100);

    expect(updated.lines[0].units[0]).toMatchObject({ endMs: 2100 });
    expect(updated.lines[0].units[0].moras[1]).toMatchObject({ endMs: 2100 });
    expect(updated.lines[0].units[1]).toMatchObject({ startMs: 2100, endMs: 2100 });
    expect(updated.lines[0].units[2]).toMatchObject({ startMs: 2100 });
    expect(updated.lines[0].units[2].moras[0]).toMatchObject({ startMs: 2100 });
  });

  it("offsets the complete timeline without producing negative timestamps", () => {
    const updated = applyTimelineOffset(timeline, -1500);

    expect(updated.lines[0]).toMatchObject({ startMs: 0, endMs: 1500 });
    expect(updated.lines[0].units[0]).toMatchObject({ startMs: 0, endMs: 500 });
  });

  it("updates a token reading and rebuilds the line reading", () => {
    const updated = updateUnitReading(timeline, 0, 0, "きみ");

    expect(updated.lines[0].units[0].reading).toBe("きみ");
    expect(updated.lines[0].reading).toBe("きみの");
  });

  it("rebuilds mora segments when a token reading changes", () => {
    const updated = updateUnitReading(timeline, 0, 0, "きょう");

    expect(updated.lines[0].units[0].moras).toEqual([
      { reading: "きょ", startMs: 1000, endMs: 1500, matched: true },
      { reading: "う", startMs: 1500, endMs: 2000, matched: true },
    ]);
  });

  it("serializes editable mora timing for cloud rendering", () => {
    expect(timelineReviewPayload(timeline)).toEqual({
      lines: [
        {
          start_ms: 1000,
          end_ms: 3000,
          tokens: [
            {
              reading: "きみ",
              start_ms: 1000,
              end_ms: 2000,
              moras: [
                { reading: "き", start_ms: 1000, end_ms: 1500 },
                { reading: "み", start_ms: 1500, end_ms: 2000 },
              ],
            },
            { reading: "の", start_ms: 2000, end_ms: 3000, moras: [] },
          ],
        },
      ],
    });
  });

  it("serializes the shared Kirakara style for cloud rendering", () => {
    expect(
      timelineReviewPayload(timeline, {
        ...DEFAULT_KIRAKARA_STYLE,
        fontSize: 72,
        upperY: 410,
      }).style,
    ).toMatchObject({ font_size: 72, upper_y: 410 });
  });
});
