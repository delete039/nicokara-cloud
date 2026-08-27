import { describe, expect, it } from "vitest";

import { inspectReviewedArtifactFiles } from "./reviewed-artifact-import";

const lyrics = {
  provider: "deepseek",
  source_text: "物語",
  lines: [
    {
      source: "物語",
      surface: "物語",
      reading: "ものがたり",
      tokens: [{ surface: "物語", reading: "ものがたり" }],
    },
  ],
  warnings: [],
};

const timeline = {
  confidence: 1,
  alignment_engine: "fa_kara_mms",
  lines: [
    {
      surface: "物語",
      reading: "ものがたり",
      start_ms: 1000,
      end_ms: 1800,
      confidence: 1,
      tokens: [],
    },
  ],
  warnings: [],
};

describe("inspectReviewedArtifactFiles", () => {
  it("detects the three current export formats without relying on filenames", async () => {
    const result = await inspectReviewedArtifactFiles([
      new File([JSON.stringify(lyrics)], "a.json"),
      new File([JSON.stringify(timeline)], "b.json"),
      new File(
        [
          "[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\nFormat: Name\n[Events]\nFormat: Layer\nDialogue: 0,x",
        ],
        "c.ass",
      ),
    ]);

    expect(result.kinds).toEqual(["lyrics", "timeline", "subtitle"]);
    expect(result.requiresRemoteVideo).toBe(true);
  });

  it("requires full video upload for ASS-only import", async () => {
    const result = await inspectReviewedArtifactFiles([
      new File(
        [
          "[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\nFormat: Name\n[Events]\nFormat: Layer\nDialogue: 0,x",
        ],
        "subtitle.ass",
      ),
    ]);

    expect(result.requiresRemoteVideo).toBe(true);
  });

  it("rejects duplicate artifact types", async () => {
    await expect(
      inspectReviewedArtifactFiles([
        new File([JSON.stringify(lyrics)], "one.json"),
        new File([JSON.stringify(lyrics)], "two.json"),
      ]),
    ).rejects.toThrow("重复");
  });
});
