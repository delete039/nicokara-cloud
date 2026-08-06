import { describe, expect, it } from "vitest";

import { inkAwareProgress } from "./kirakara-progress";

describe("inkAwareProgress", () => {
  it("extends the mask from the left ink edge through the right stroke", () => {
    const result = inkAwareProgress({
      rawProgress: 0.25,
      fontSize: 64,
      strokeWidth: 5,
      width: 40,
      inkLeft: 0,
      inkRight: 40,
      layoutWidth: 64,
    });

    expect(result.total).toBe(74);
    expect(result.percentage).toBeCloseTo(16.2162, 4);
    expect(result.canvasWidth).toBeCloseTo(71, 4);
  });
});
