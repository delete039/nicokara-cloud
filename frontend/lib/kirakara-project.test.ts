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
    const twoRubyTimeline: KirakaraTimeline = {
      ...timeline,
      lines: [
        {
          ...timeline.lines[0],
          text: "今日歌",
          reading: "きょううた",
          units: [
            ...timeline.lines[0].units,
            {
              text: "歌",
              reading: "うた",
              startMs: 1500,
              endMs: 1800,
              moras: [
                { reading: "う", startMs: 1500, endMs: 1650, matched: true },
                { reading: "た", startMs: 1650, endMs: 1800, matched: true },
              ],
            },
          ],
        },
      ],
    };
    const lrc = serializeKirakaraLrc(twoRubyTimeline);

    const lines = lrc.split("\n");
    expect(lines[0]).toBe(
      "[00:01:00]今日[00:01:50]も[00:01:50]歌[00:01:80]",
    );
    expect(lines.slice(1)).toEqual([
      "@Ruby1=今日,きょ[00:00:20]う,[00:01:00],[00:01:50]",
      "@Ruby2=歌,う[00:00:15]た,[00:01:50],[00:01:80]",
    ]);
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
    const projectBody = project.slice(lyricStart + 3);
    expect(projectBody).toBe(serializeKirakaraLrc(timeline));
    expect(projectBody.indexOf("[00:01:00]今日")).toBeLessThan(
      projectBody.indexOf("@Ruby1=今日"),
    );
  });

  it("REQ-STYLE-KRL-01 reuses upstream KRL fields and preserves shadow extensions", () => {
    const project = buildKirakaraProject(timeline, {
      ...DEFAULT_KIRAKARA_STYLE,
      fontBold: false,
      letterSpacing: 3,
      rubyLetterSpacing: 2,
      rubyOffset: 7,
      strokeColorBefore: "#123456",
      strokeColorAfter: "#abcdef",
      shadowColor: "#654321",
      shadowDepth: 4,
      horizontalMargin: 90,
    });
    const lyricStart = project.indexOf("\n\n\n");
    const config = JSON.parse(project.slice("config ".length, lyricStart));

    expect(config).toMatchObject({
      fontBold: false,
      letterSpacing: 3,
      rubyLetterSpacing: 2,
      rubyOffset: 7,
      strokeColorBefore: "#123456",
      strokeColorAfter: "#abcdef",
      shadowColor: "#654321",
      shadowDepth: 4,
      line1X: 90,
      line2Right: 90,
    });
  });

  it("keeps visible paragraph separators at Kirakara timing boundaries", () => {
    const paragraphTimeline: KirakaraTimeline = {
      confidence: 1,
      warnings: [],
      durationMs: 11_500,
      lines: [
        {
          text: "line-1",
          reading: "line-1",
          startMs: 1_000,
          endMs: 1_500,
          units: [{ text: "line-1", reading: "line-1", startMs: 1_000, endMs: 1_500, moras: [] }],
        },
        {
          text: "line-2",
          reading: "line-2",
          startMs: 10_000,
          endMs: 11_500,
          units: [{ text: "line-2", reading: "line-2", startMs: 10_000, endMs: 11_500, moras: [] }],
        },
      ],
    };

    expect(serializeKirakaraLrc(paragraphTimeline)).toContain(
      "[00:01:00]line-1[00:01:50]\n\n[00:10:00]line-2[00:11:50]",
    );
  });
});
