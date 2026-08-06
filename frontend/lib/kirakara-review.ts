import {
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
    }>;
  }>;
  style?: ReturnType<typeof kirakaraStylePayload>;
};

function durationMs(timeline: KirakaraTimeline): number {
  return timeline.lines.reduce((latest, line) => Math.max(latest, line.endMs), 0);
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
      return {
        ...unit,
        reading: nextReading,
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
    lines: timeline.lines.map((line) => ({
      start_ms: line.startMs,
      end_ms: line.endMs,
      tokens: line.units.map((unit) => ({
        reading: unit.reading,
        start_ms: unit.startMs,
        end_ms: unit.endMs,
      })),
    })),
    ...(style ? { style: kirakaraStylePayload(style) } : {}),
  };
}
