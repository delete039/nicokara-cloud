import {
  closeLineMoraGaps,
  kanjiRuby,
  type KirakaraLine,
  type KirakaraMora,
  type KirakaraRenderUnit,
  type KirakaraTimeline,
} from "./kirakara-timeline";
import { kirakaraStylePayload, type KirakaraStyle } from "./kirakara-style";

export type TimelineReviewPayload = {
  lines: Array<{
    start_ms: number;
    end_ms: number;
    tokens: Array<{
      reading: string;
      start_ms: number;
      end_ms: number;
      moras: Array<{
        reading: string;
        start_ms: number;
        end_ms: number;
      }>;
    }>;
  }>;
  style?: ReturnType<typeof kirakaraStylePayload>;
};

function durationMs(timeline: KirakaraTimeline): number {
  return timeline.lines.reduce((latest, line) => Math.max(latest, line.endMs), 0);
}

export function timelineDragOffsetMs(
  deltaPixels: number,
  trackWidthPixels: number,
  timelineDurationMs: number,
): number {
  if (
    !Number.isFinite(deltaPixels) ||
    !Number.isFinite(trackWidthPixels) ||
    !Number.isFinite(timelineDurationMs) ||
    trackWidthPixels <= 0 ||
    timelineDurationMs <= 0
  ) return 0;
  return Math.round(deltaPixels / trackWidthPixels * timelineDurationMs);
}

function mapRange(value: number, oldStart: number, oldEnd: number, nextStart: number, nextEnd: number) {
  if (oldEnd <= oldStart) return nextStart;
  const ratio = (value - oldStart) / (oldEnd - oldStart);
  return Math.round(nextStart + ratio * (nextEnd - nextStart));
}

function scaleMora(
  mora: KirakaraMora,
  oldStart: number,
  oldEnd: number,
  nextStart: number,
  nextEnd: number,
): KirakaraMora {
  return {
    ...mora,
    startMs: mapRange(mora.startMs, oldStart, oldEnd, nextStart, nextEnd),
    endMs: mapRange(mora.endMs, oldStart, oldEnd, nextStart, nextEnd),
  };
}

function scaleUnit(
  unit: KirakaraRenderUnit,
  oldStart: number,
  oldEnd: number,
  nextStart: number,
  nextEnd: number,
): KirakaraRenderUnit {
  return {
    ...unit,
    startMs: mapRange(unit.startMs, oldStart, oldEnd, nextStart, nextEnd),
    endMs: mapRange(unit.endMs, oldStart, oldEnd, nextStart, nextEnd),
    moras: unit.moras.map((mora) =>
      scaleMora(mora, oldStart, oldEnd, nextStart, nextEnd),
    ),
  };
}

export function updateLineRange(
  timeline: KirakaraTimeline,
  lineIndex: number,
  startMs: number,
  endMs: number,
): KirakaraTimeline {
  const nextStart = Math.max(0, Math.round(startMs));
  const nextEnd = Math.round(endMs);
  if (nextEnd <= nextStart) throw new RangeError("结束时间必须晚于开始时间");
  const current = timeline.lines[lineIndex];
  if (!current) throw new RangeError("歌词行不存在");

  const lines = timeline.lines.map((line, index): KirakaraLine =>
    index !== lineIndex
      ? line
      : {
          ...line,
          startMs: nextStart,
          endMs: nextEnd,
          units: line.units.map((unit) =>
            scaleUnit(
              unit,
              line.startMs,
              line.endMs,
              nextStart,
              nextEnd,
            ),
          ),
        },
  );
  return { ...timeline, lines, durationMs: durationMs({ ...timeline, lines }) };
}

export function applyTimelineOffset(
  timeline: KirakaraTimeline,
  offsetMs: number,
): KirakaraTimeline {
  const shift = (value: number) => Math.max(0, Math.round(value + offsetMs));
  const lines = timeline.lines.map((line) => ({
    ...line,
    startMs: shift(line.startMs),
    endMs: shift(line.endMs),
    units: line.units.map((unit) => ({
      ...unit,
      startMs: shift(unit.startMs),
      endMs: shift(unit.endMs),
      moras: unit.moras.map((mora) => ({
        ...mora,
        startMs: shift(mora.startMs),
        endMs: shift(mora.endMs),
      })),
    })),
  }));
  return { ...timeline, lines, durationMs: durationMs({ ...timeline, lines }) };
}

export function applyLineOffset(
  timeline: KirakaraTimeline,
  lineIndex: number,
  offsetMs: number,
): KirakaraTimeline {
  const current = timeline.lines[lineIndex];
  if (!current) throw new RangeError("歌词行不存在");

  const previous = timeline.lines[lineIndex - 1];
  const next = timeline.lines[lineIndex + 1];
  const duration = current.endMs - current.startMs;
  const minimumStart = Math.max(0, previous?.endMs ?? 0);
  const maximumStart = next
    ? Math.max(minimumStart, next.startMs - duration)
    : Number.POSITIVE_INFINITY;
  const nextStart = Math.min(
    maximumStart,
    Math.max(minimumStart, Math.round(current.startMs + offsetMs)),
  );
  const shift = nextStart - current.startMs;
  const shiftTime = (value: number) => value + shift;
  const lines = timeline.lines.map((line, index): KirakaraLine => {
    if (index !== lineIndex) return line;
    return {
      ...line,
      startMs: shiftTime(line.startMs),
      endMs: shiftTime(line.endMs),
      units: line.units.map((unit) => ({
        ...unit,
        startMs: shiftTime(unit.startMs),
        endMs: shiftTime(unit.endMs),
        moras: unit.moras.map((mora) => ({
          ...mora,
          startMs: shiftTime(mora.startMs),
          endMs: shiftTime(mora.endMs),
        })),
      })),
    };
  });
  return { ...timeline, lines, durationMs: durationMs({ ...timeline, lines }) };
}

export type LineEdge = "start" | "end";

const MIN_RESIZED_LINE_DURATION_MS = 100;

export function applyLineEdgeOffset(
  timeline: KirakaraTimeline,
  lineIndex: number,
  edge: LineEdge,
  offsetMs: number,
): KirakaraTimeline {
  const current = timeline.lines[lineIndex];
  if (!current) throw new RangeError("歌词行不存在");

  const previous = timeline.lines[lineIndex - 1];
  const next = timeline.lines[lineIndex + 1];
  const currentDuration = current.endMs - current.startMs;
  const minimumDuration = Math.min(
    MIN_RESIZED_LINE_DURATION_MS,
    Math.max(1, currentDuration),
  );
  const offset = Number.isFinite(offsetMs) ? Math.round(offsetMs) : 0;

  if (edge === "start") {
    const minimumStart = Math.max(0, previous?.endMs ?? 0);
    const maximumStart = current.endMs - minimumDuration;
    const nextStart = Math.min(
      maximumStart,
      Math.max(minimumStart, current.startMs + offset),
    );
    return updateLineRange(timeline, lineIndex, nextStart, current.endMs);
  }

  const minimumEnd = current.startMs + minimumDuration;
  const maximumEnd = next?.startMs ?? Number.POSITIVE_INFINITY;
  const nextEnd = Math.min(
    maximumEnd,
    Math.max(minimumEnd, current.endMs + offset),
  );
  return updateLineRange(timeline, lineIndex, current.startMs, nextEnd);
}

const MIN_MORA_DURATION_MS = 10;
const SMALL_KANA = new Set([..."ゃゅょぁぃぅぇぉゎゕゖ"]);

function splitReadingMoras(reading: string): string[] {
  const normalized = reading.normalize("NFKC").replace(
    /[\u30a1-\u30f6]/gu,
    (character) => String.fromCharCode(character.charCodeAt(0) - 0x60),
  );
  const moras: string[] = [];
  for (const character of normalized) {
    if (/^[\p{P}\p{S}\s]$/u.test(character)) continue;
    if (SMALL_KANA.has(character) && moras.length > 0) {
      moras[moras.length - 1] += character;
    } else {
      moras.push(character);
    }
  }
  return moras;
}

type MoraReference = {
  unitIndex: number;
  moraIndex: number;
};

function lineMoraReferences(line: KirakaraLine): MoraReference[] {
  return line.units.flatMap((unit, unitIndex) =>
    unit.moras.map((_, moraIndex) => ({ unitIndex, moraIndex })),
  );
}

export function updateMoraBoundary(
  timeline: KirakaraTimeline,
  lineIndex: number,
  boundaryIndex: number,
  timeMs: number,
): KirakaraTimeline {
  const line = timeline.lines[lineIndex];
  if (!line) throw new RangeError("歌词行不存在");
  const references = lineMoraReferences(line);
  const left = references[boundaryIndex];
  const right = references[boundaryIndex + 1];
  if (!left || !right) throw new RangeError("Mora 分界不存在");

  const leftUnit = line.units[left.unitIndex];
  const rightUnit = line.units[right.unitIndex];
  const leftStart = left.moraIndex === 0
    ? leftUnit.startMs
    : leftUnit.moras[left.moraIndex - 1].endMs;
  const rightEnd = right.moraIndex === rightUnit.moras.length - 1
    ? rightUnit.endMs
    : rightUnit.moras[right.moraIndex].endMs;
  const availableDuration = Math.max(0, rightEnd - leftStart);
  const minimumDuration = Math.min(
    MIN_MORA_DURATION_MS,
    Math.floor(availableDuration / 2),
  );
  const nextBoundary = Math.min(
    rightEnd - minimumDuration,
    Math.max(leftStart + minimumDuration, Math.round(timeMs)),
  );

  const lines = timeline.lines.map((candidate, candidateIndex): KirakaraLine => {
    if (candidateIndex !== lineIndex) return candidate;
    return {
      ...candidate,
      units: candidate.units.map((unit, unitIndex) => {
        if (unitIndex < left.unitIndex || unitIndex > right.unitIndex) return unit;
        if (unitIndex > left.unitIndex && unitIndex < right.unitIndex) {
          return { ...unit, startMs: nextBoundary, endMs: nextBoundary };
        }
        const moras = unit.moras.map((mora, moraIndex) => {
          if (unitIndex === left.unitIndex && moraIndex === left.moraIndex) {
            return { ...mora, endMs: nextBoundary };
          }
          if (unitIndex === right.unitIndex && moraIndex === right.moraIndex) {
            return { ...mora, startMs: nextBoundary };
          }
          return mora;
        });
        return {
          ...unit,
          ...(unitIndex === left.unitIndex && left.unitIndex !== right.unitIndex
            ? { endMs: nextBoundary }
            : {}),
          ...(unitIndex === right.unitIndex && left.unitIndex !== right.unitIndex
            ? { startMs: nextBoundary }
            : {}),
          moras,
        };
      }),
    };
  });
  return { ...timeline, lines };
}

export function updateUnitReading(
  timeline: KirakaraTimeline,
  lineIndex: number,
  unitIndex: number,
  reading: string,
): KirakaraTimeline {
  const line = timeline.lines[lineIndex];
  if (!line?.units[unitIndex]) throw new RangeError("歌词词元不存在");
  const lines = timeline.lines.map((candidate, candidateIndex) => {
    if (candidateIndex !== lineIndex) return candidate;
    const units = candidate.units.map((unit, index) => {
      if (index !== unitIndex) return unit;
      const nextReading = reading.trim();
      const moraReadings = splitReadingMoras(nextReading);
      const duration = unit.endMs - unit.startMs;
      return {
        ...unit,
        reading: nextReading,
        moras: nextReading === unit.reading
          ? unit.moras
          : moraReadings.map((moraReading, moraIndex) => ({
              reading: moraReading,
              startMs: unit.startMs + Math.floor(
                duration * moraIndex / moraReadings.length,
              ),
              endMs: unit.startMs + Math.floor(
                duration * (moraIndex + 1) / moraReadings.length,
              ),
              matched: true,
            })),
        ruby: kanjiRuby(unit.text, nextReading),
      };
    });
    return { ...candidate, units, reading: units.map((unit) => unit.reading).join("") };
  });
  return { ...timeline, lines };
}

export function timelineReviewPayload(
  timeline: KirakaraTimeline,
  style?: KirakaraStyle,
): TimelineReviewPayload {
  return {
    lines: timeline.lines.map((sourceLine) => {
      const line = closeLineMoraGaps(sourceLine);
      return {
        start_ms: line.startMs,
        end_ms: line.endMs,
        tokens: line.units.map((unit) => ({
          reading: unit.reading,
          start_ms: unit.startMs,
          end_ms: unit.endMs,
          moras: unit.moras.map((mora) => ({
            reading: mora.reading,
            start_ms: mora.startMs,
            end_ms: mora.endMs,
          })),
        })),
      };
    }),
    ...(style ? { style: kirakaraStylePayload(style) } : {}),
  };
}
