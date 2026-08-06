import { describe, expect, it } from "vitest";

import type { KirakaraTimeline } from "./kirakara-timeline";
import {
  applyTimelineOffset,
  timelineReviewPayload,
  updateLineRange,
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

  it("serializes only editable timing and reading fields for cloud rendering", () => {
    expect(timelineReviewPayload(timeline)).toEqual({
      lines: [
        {
          start_ms: 1000,
          end_ms: 3000,
          tokens: [
            { reading: "きみ", start_ms: 1000, end_ms: 2000 },
            { reading: "の", start_ms: 2000, end_ms: 3000 },
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
