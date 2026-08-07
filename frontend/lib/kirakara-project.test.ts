import { describe, expect, it } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";
import {
  buildKirakaraProject,
  serializeKirakaraLrc,
} from "./kirakara-project";
import type { KirakaraTimeline } from "./kirakara-timeline";

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 1800,
  lines: [
    {
      text: "今日も",
      reading: "きょうも",
      startMs: 1000,
      endMs: 1800,
      units: [
        {
          text: "今日",
          reading: "きょう",
          startMs: 1000,
          endMs: 1500,
          moras: [
            { reading: "きょ", startMs: 1000, endMs: 1200, matched: true },
            { reading: "う", startMs: 1200, endMs: 1500, matched: true },
          ],
        },
        {
          text: "も",
          reading: "も",
          startMs: 1500,
          endMs: 1800,
          moras: [],
        },
      ],
    },
  ],
};

describe("Kirakara project compatibility", () => {
  it("serializes cloud timing as Kirakara @Ruby LRC without inferred ruby parsing", () => {
    const lrc = serializeKirakaraLrc(timeline);

    expect(lrc).toContain(
      "@Ruby=今日,きょ[00:00:20]う,[00:01:00],[00:01:50]",
    );
    expect(lrc).toContain(
      "[00:01:00]今日[00:01:50]も[00:01:80]",
    );
    expect(lrc).not.toContain("{今日|");
  });

  it("builds the exact config-plus-LRC KRL structure accepted by Kirakara", () => {
    const project = buildKirakaraProject(timeline, {
      ...DEFAULT_KIRAKARA_STYLE,
      fontFamily: "'Hiragino Sans', sans-serif",
    });

    expect(project).toMatch(/^config \{/);
    const lyricStart = project.indexOf("\n\n\n");
    expect(lyricStart).toBeGreaterThan(0);
    const config = JSON.parse(project.slice("config ".length, lyricStart));
    expect(config).toMatchObject({
      fontFamily: "'Hiragino Sans', sans-serif",
      fontSize: 64,
      rubySize: 26,
      line1Y: 430,
      line2Y: 563,
      letterSpacing: 9,
      rubyIsolateEnabled: true,
    });
    expect(project.slice(lyricStart + 3)).toBe(serializeKirakaraLrc(timeline));
  });
});
