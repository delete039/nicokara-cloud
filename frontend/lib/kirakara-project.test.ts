import { describe, expect, it } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";
import {
  attachKirakaraRomaji,
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
  it("creates the secondary layer only after the final mora timing is available", () => {
    const exported = attachKirakaraRomaji(timeline);

    expect(exported).not.toBe(timeline);
    expect(exported.lines[0].units[0].romajiMoras).toEqual(["kyo", "u"]);
    expect(exported.lines[0].units[1].romajiMoras).toEqual(["mo"]);
    expect(exported.lines[0].units[0].romajiPosition).toBe("above");
    expect(timeline.lines[0].units[0].romajiMoras).toBeUndefined();
  });

  it("serializes cloud timing as SUG-compatible inline double-ruby LRC", () => {
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
    const lrc = serializeKirakaraLrc(twoRubyTimeline, {
      includeRomaji: true,
    });

    expect(lrc).toBe(
      "{今日|[00:01:00]きょ[00:01:20]う>[00:01:00]kyo[00:01:20]u}{も|>[00:01:50]mo}{歌|[00:01:50]う[00:01:65]た>[00:01:50]u[00:01:65]ta}[00:01:80]",
    );
    expect(lrc).not.toContain("@Ruby");
  });

  it("keeps KRL in SUG-compatible kana-first order even when preview uses romaji above", () => {
    const previewOnlyOptions = {
      includeRomaji: true,
      romajiPosition: "above",
    } as const;

    expect(serializeKirakaraLrc(timeline, previewOnlyOptions)).toBe(
      "{今日|[00:01:00]きょ[00:01:20]う>[00:01:00]kyo[00:01:20]u}{も|>[00:01:50]mo}[00:01:80]",
    );

    const project = buildKirakaraProject(
      timeline,
      DEFAULT_KIRAKARA_STYLE,
      previewOnlyOptions,
    );
    const lyricStart = project.indexOf("\n\n\n");
    const config = JSON.parse(project.slice("config ".length, lyricStart));
    expect(config).toMatchObject({
      rubySize: DEFAULT_KIRAKARA_STYLE.rubySize,
      rubyLetterSpacing: DEFAULT_KIRAKARA_STYLE.rubyLetterSpacing,
      ruby2Size: 22,
      ruby2LetterSpacing: 1,
    });
  });

  it("defaults to kana-only inline ruby until romaji is enabled", () => {
    expect(serializeKirakaraLrc(timeline)).toBe(
      "{今日|[00:01:00]きょ[00:01:20]う}[00:01:50]も[00:01:80]",
    );
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
      rubyBold: true,
      ruby2Size: 22,
      ruby2Offset: 3,
      ruby2LetterSpacing: 1,
      ruby2Bold: true,
      ruby2StrokeWidth: 2,
      bgColor: "#008000",
      indicatorFillColor: "#ebebeb",
      songTitle: {
        enabled: false,
        durationSec: 6,
        textFade: true,
        prelude: {
          enabled: false,
          fadeEnabled: false,
          fadeDurationMs: 666,
        },
        groups: [],
      },
    });
    const projectBody = project.slice(lyricStart + 3);
    expect(projectBody).toBe(serializeKirakaraLrc(timeline));
    expect(projectBody).toContain("{今日|");
    expect(projectBody).not.toContain("@Ruby");
  });

  it("keeps the supplied SUG template field order and excludes webpage-only romaji style", () => {
    const project = buildKirakaraProject(timeline, {
      ...DEFAULT_KIRAKARA_STYLE,
      romajiFollowRuby: false,
      romajiSize: 48,
      romajiLetterSpacing: 9,
      romajiOffset: 14,
    }, { includeRomaji: true });
    const lyricStart = project.indexOf("\n\n\n");
    const config = JSON.parse(project.slice("config ".length, lyricStart));

    expect(Object.keys(config)).toEqual([
      "fontSize", "letterSpacing", "fontFamily", "fontBold",
      "rubySize", "rubyOffset", "rubyLetterSpacing", "rubyBold", "rubyStrokeWidth",
      "ruby2Size", "ruby2Offset", "ruby2LetterSpacing", "ruby2Bold", "ruby2StrokeWidth",
      "rubyIsolateEnabled", "colorBefore", "colorAfter", "strokeColorBefore",
      "strokeColorAfter", "strokeWidth", "line1X", "line1Y", "line2Right", "line2Y",
      "bgColor", "fadeEnabled", "fadeParagraphOnly", "fadeDurationMs", "indicatorEnabled",
      "indicatorDuration", "indicatorSize", "indicatorSpacing", "indicatorStrokeWidth",
      "indicatorStrokeColor", "indicatorFillColor", "indicatorFadeRatio", "indicatorOffsetX",
      "indicatorOffsetY", "characterProfiles", "roleLabelPrefix", "roleLabelSeparator",
      "roleLabelSuffix", "songTitle",
    ]);
    expect(config.roleLabelSuffix).toBe("：");
    expect(project.slice(lyricStart + 3)).toContain("{今日|[00:01:00]きょ");
    expect(project).not.toContain("@Ruby");
  });

  it("REQ-STYLE-KRL-01 reuses upstream KRL fields without browser render extensions", () => {
    const project = buildKirakaraProject(timeline, {
      ...DEFAULT_KIRAKARA_STYLE,
      fontBold: false,
      letterSpacing: 3,
      rubyLetterSpacing: 2,
      rubyOffset: 7,
      strokeColorBefore: "#123456",
      strokeColorAfter: "#abcdef",
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
      line1X: 90,
      line2Right: 90,
    });
    expect(config).not.toHaveProperty("shadowColor");
    expect(config).not.toHaveProperty("shadowDepth");
    expect(config).not.toHaveProperty("bgImageOpacity");
  });

  it("keeps preview-only romaji styling out of the KRL config", () => {
    const previewStyle = {
      ...DEFAULT_KIRAKARA_STYLE,
      romajiFollowRuby: false,
      romajiSize: 48,
      romajiLetterSpacing: 9,
      romajiOffset: 14,
    } as const;
    const project = buildKirakaraProject(
      timeline,
      previewStyle,
      { includeRomaji: true },
    );
    const lyricStart = project.indexOf("\n\n\n");
    const config = JSON.parse(project.slice("config ".length, lyricStart));

    expect(config).toMatchObject({
      ruby2Size: 22,
      ruby2LetterSpacing: 1,
      ruby2Offset: 3,
    });
    expect(config).not.toHaveProperty("romajiSize");
    expect(config).not.toHaveProperty("romajiLetterSpacing");
    expect(config).not.toHaveProperty("romajiOffset");
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
