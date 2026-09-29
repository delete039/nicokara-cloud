import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "./kirakara-style";
import {
  layoutKirakaraParagraphs,
  splitReadingMoras,
  type KirakaraRomajiPosition,
  type KirakaraRenderUnit,
  type KirakaraTimeline,
} from "./kirakara-timeline";
import { romanizeReadingMoras } from "./japanese-romaji";

const KANJI = /[\u3400-\u4dbf\u4e00-\u9fff]/u;

export function formatKirakaraTime(milliseconds: number): string {
  const centiseconds = Math.max(0, Math.round(milliseconds / 10));
  const minutes = Math.floor(centiseconds / 6000);
  const seconds = Math.floor((centiseconds % 6000) / 100);
  const fraction = centiseconds % 100;
  return `[${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}:${String(fraction).padStart(2, "0")}]`;
}

export type KirakaraProjectOptions = {
  includeRomaji?: boolean;
};

function isPunctuationOnly(text: string): boolean {
  return [...text].every((character) => /^[\p{P}\p{S}\s]$/u.test(character));
}

function timedMoras(unit: KirakaraRenderUnit) {
  if (unit.moras.length > 0) return unit.moras;
  const readings = splitReadingMoras(unit.reading);
  if (readings.length === 0) return [];
  const duration = Math.max(0, unit.endMs - unit.startMs);
  return readings.map((reading, index) => ({
    reading,
    startMs: unit.startMs + Math.floor(duration * index / readings.length),
    endMs: unit.startMs + Math.floor(duration * (index + 1) / readings.length),
  }));
}

/**
 * Attach the optional secondary layer without changing the aligned timeline.
 *
 * This intentionally runs after review/alignment has produced final mora
 * boundaries.  The renderer can therefore receive either this cloned timeline
 * (kana + romaji) or the original timeline (kana only) without re-aligning.
 */
export function attachKirakaraRomaji(
  timeline: KirakaraTimeline,
  position: KirakaraRomajiPosition = "above",
): KirakaraTimeline {
  return {
    ...timeline,
    lines: timeline.lines.map((line) => ({
      ...line,
      units: line.units.map((unit) => {
        const readings = timedMoras(unit).map((mora) => mora.reading);
        return {
          ...unit,
          romajiPosition: position,
          romajiMoras: readings.length
            ? romanizeReadingMoras(readings, unit.text)
            : [],
        };
      }),
    })),
  };
}

function taggedLayer(
  readings: string[],
  timestamps: number[],
): string {
  return readings
    .map((reading, index) => `${formatKirakaraTime(timestamps[index] ?? timestamps[0] ?? 0)}${reading}`)
    .join("");
}

function unitKrl(unit: KirakaraRenderUnit, includeRomaji: boolean): string {
  if (isPunctuationOnly(unit.text) || !unit.reading.trim()) {
    return isPunctuationOnly(unit.text)
      ? unit.text
      : `${formatKirakaraTime(unit.startMs)}${unit.text}`;
  }

  const moras = timedMoras(unit);
  const isKanaReading = /[\u3040-\u30ff]/u.test(unit.reading);
  if (!isKanaReading || moras.length === 0) {
    return `${formatKirakaraTime(unit.startMs)}${unit.text}`;
  }

  const readings = moras.map((mora) => mora.reading);
  const timestamps = moras.map((mora) => mora.startMs);
  const primary = taggedLayer(readings, timestamps);
  if (!includeRomaji) {
    return KANJI.test(unit.text)
      ? `{${unit.text}|${primary}}`
      : `${formatKirakaraTime(unit.startMs)}${unit.text}`;
  }

  const romaji = taggedLayer(
    unit.romajiMoras ?? romanizeReadingMoras(readings, unit.text),
    timestamps,
  );
  if (KANJI.test(unit.text)) return `{${unit.text}|${primary}>${romaji}}`;
  return `{${unit.text}|>${romaji}}`;
}

export function serializeKirakaraLrc(
  timeline: KirakaraTimeline,
  options: KirakaraProjectOptions = {},
): string {
  const includeRomaji = options.includeRomaji ?? false;
  const exportTimeline = includeRomaji
    ? attachKirakaraRomaji(timeline)
    : timeline;
  const layout = layoutKirakaraParagraphs(exportTimeline.lines);
  const lyricLines = layout.map(({ line, paragraph }, index) => {
    const body = line.units
      .map((unit) => unitKrl(unit, includeRomaji))
      .join("");
    const paragraphBreak = index > 0 && paragraph !== layout[index - 1].paragraph
      ? "\n"
      : "";
    return `${paragraphBreak}${body}${formatKirakaraTime(line.endMs)}`;
  });
  return lyricLines.join("\n");
}

export function kirakaraProjectConfig(style: KirakaraStyle) {
  const value = normalizeKirakaraStyle(style);
  return {
    fontSize: value.fontSize,
    letterSpacing: value.letterSpacing,
    fontFamily: value.fontFamily,
    fontBold: value.fontBold,
    rubySize: value.rubySize,
    rubyOffset: value.rubyOffset,
    rubyLetterSpacing: value.rubyLetterSpacing,
    rubyBold: true,
    rubyStrokeWidth: Math.round(value.strokeWidth * 0.8),
    ruby2Size: 22,
    ruby2Offset: 3,
    ruby2LetterSpacing: 1,
    ruby2Bold: true,
    ruby2StrokeWidth: 2,
    rubyIsolateEnabled: true,
    colorBefore: value.colorBefore,
    colorAfter: value.colorAfter,
    strokeColorBefore: value.strokeColorBefore,
    strokeColorAfter: value.strokeColorAfter,
    strokeWidth: value.strokeWidth,
    line1X: value.horizontalMargin,
    line1Y: value.upperY,
    line2Right: value.horizontalMargin,
    line2Y: value.lowerY,
    bgColor: "#008000",
    fadeEnabled: true,
    fadeParagraphOnly: true,
    fadeDurationMs: 666,
    indicatorEnabled: true,
    indicatorDuration: 3,
    indicatorSize: 34,
    indicatorSpacing: 12,
    indicatorStrokeWidth: 3,
    indicatorStrokeColor: "#000000",
    indicatorFillColor: "#ebebeb",
    indicatorFadeRatio: 0,
    indicatorOffsetX: 0,
    indicatorOffsetY: 8,
    characterProfiles: {},
    roleLabelPrefix: "",
    roleLabelSeparator: "",
    roleLabelSuffix: "：",
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
  };
}

export function buildKirakaraProject(
  timeline: KirakaraTimeline,
  style: KirakaraStyle = DEFAULT_KIRAKARA_STYLE,
  options: KirakaraProjectOptions = {},
): string {
  const config = JSON.stringify(kirakaraProjectConfig(style), null, 4);
  return `config ${config}\n\n\n${serializeKirakaraLrc(timeline, options)}`;
}

export function kirakaraProjectFileName(videoName: string): string {
  const stem = videoName.replace(/\.[^.]+$/u, "").trim() || "nicokara";
  return `${stem.replace(/[\\/:*?"<>|]/gu, "_")}.krl`;
}
