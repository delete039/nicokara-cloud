import { describe, expect, it } from "vitest";

import { updateUnitReading } from "./kirakara-review";
import type { KirakaraTimeline } from "./kirakara-timeline";

describe("Kirakara ruby review", () => {
  it("rebuilds kanji ruby after a manual reading correction", () => {
    const timeline: KirakaraTimeline = {
      confidence: 1,
      warnings: [],
      durationMs: 2000,
      lines: [
        {
          text: "君の",
          reading: "くんの",
          startMs: 1000,
          endMs: 2000,
          units: [
            {
              text: "君",
              reading: "くん",
              startMs: 1000,
              endMs: 1600,
              moras: [],
              ruby: [{ text: "くん", startCharacter: 0, endCharacter: 1 }],
            },
            {
              text: "の",
              reading: "の",
              startMs: 1600,
              endMs: 2000,
              moras: [],
              ruby: [],
            },
          ],
        },
      ],
    };

    const updated = updateUnitReading(timeline, 0, 0, "きみ");

    expect(updated.lines[0].reading).toBe("きみの");
    expect(updated.lines[0].units[0].ruby).toEqual([
      { text: "きみ", startCharacter: 0, endCharacter: 1 },
    ]);
  });
});
