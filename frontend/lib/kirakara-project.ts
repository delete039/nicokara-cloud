import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "./kirakara-style";
import type { KirakaraRenderUnit, KirakaraTimeline } from "./kirakara-timeline";

const KANJI = /[\u3400-\u4dbf\u4e00-\u9fff]/u;

export function formatKirakaraTime(milliseconds: number): string {
  const centiseconds = Math.max(0, Math.round(milliseconds / 10));
  const minutes = Math.floor(centiseconds / 6000);
  const seconds = Math.floor((centiseconds % 6000) / 100);
  const fraction = centiseconds % 100;
  return `[${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}:${String(fraction).padStart(2, "0")}]`;
}

function rubyReading(unit: KirakaraRenderUnit): string {
  if (unit.moras.length === 0) return unit.reading;
  return unit.moras
    .map((mora, index) => {
      if (index === unit.moras.length - 1) return mora.reading;
      return `${mora.reading}${formatKirakaraTime(mora.endMs - unit.startMs)}`;
    })
    .join("");
}

function rubyDirectives(timeline: KirakaraTimeline): string[] {
  return timeline.lines.flatMap((line) =>
    line.units
      .filter(
        (unit) =>
          KANJI.test(unit.text) &&
          unit.reading.trim().length > 0 &&
          !/[\r\n,]/u.test(unit.text),
      )
      .map(
        (unit) =>
          `@Ruby=${unit.text},${rubyReading(unit)},${formatKirakaraTime(unit.startMs)},${formatKirakaraTime(unit.endMs)}`,
      ),
  );
}

export function serializeKirakaraLrc(timeline: KirakaraTimeline): string {
  const directives = rubyDirectives(timeline);
  const lyricLines = timeline.lines.map((line) => {
    const body = line.units
      .map((unit) => `${formatKirakaraTime(unit.startMs)}${unit.text}`)
      .join("");
    return `${body}${formatKirakaraTime(line.endMs)}`;
  });
  return [...directives, ...lyricLines].join("\n");
}

export function kirakaraProjectConfig(style: KirakaraStyle) {
  const value = normalizeKirakaraStyle(style);
  return {
    fontSize: value.fontSize,
    letterSpacing: 9,
    fontFamily: value.fontFamily,
    fontBold: true,
    rubySize: value.rubySize,
    rubyOffset: 4,
    rubyLetterSpacing: 5,
    rubyBold: false,
    rubyStrokeWidth: 4,
    rubyIsolateEnabled: true,
    colorBefore: value.colorBefore,
    colorAfter: value.colorAfter,
    strokeColorBefore: "#000000",
    strokeColorAfter: "#ffffff",
    strokeWidth: value.strokeWidth,
    line1X: 128,
    line1Y: value.upperY,
    line2Right: 128,
    line2Y: value.lowerY,
    bgColor: "#005500",
    fadeEnabled: true,
    fadeParagraphOnly: true,
    fadeDurationMs: 666,
    indicatorEnabled: true,
    indicatorDuration: 3,
    indicatorSize: 34,
    indicatorSpacing: 12,
    indicatorStrokeWidth: 3,
    indicatorStrokeColor: "#000000",
    indicatorFillColor: "#ffffff",
    indicatorFadeRatio: 0,
    indicatorOffsetX: 0,
    indicatorOffsetY: 8,
    bgImageOpacity: 1,
    characterProfiles: {},
    roleLabelPrefix: "",
    roleLabelSeparator: "",
    roleLabelSuffix: "",
    songTitle: { enabled: false },
  };
}

export function buildKirakaraProject(
  timeline: KirakaraTimeline,
  style: KirakaraStyle = DEFAULT_KIRAKARA_STYLE,
): string {
  const config = JSON.stringify(kirakaraProjectConfig(style), null, 4);
  return `config ${config}\n\n\n${serializeKirakaraLrc(timeline)}`;
}

export function kirakaraProjectFileName(videoName: string): string {
  const stem = videoName.replace(/\.[^.]+$/u, "").trim() || "nicokara";
  return `${stem.replace(/[\\/:*?"<>|]/gu, "_")}.krl`;
}
