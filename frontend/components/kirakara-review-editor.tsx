"use client";

import { GripVertical, RotateCcw, TimerReset } from "lucide-react";
import {
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  applyLineEdgeOffset,
  applyTimelineOffset,
  timelineDragOffsetMs,
  updateLineRange,
  updateMoraBoundary,
  updateUnitReading,
} from "@/lib/kirakara-review";
import type {
  KirakaraLine,
  KirakaraTimeline,
} from "@/lib/kirakara-timeline";

type TimingDragTarget =
  | { kind: "line-edge"; edge: "start" | "end" }
  | { kind: "mora-boundary"; boundaryIndex: number; baseTimeMs: number };

type TimingDrag = {
  pointerId: number;
  lineIndex: number;
  target: TimingDragTarget;
  startClientX: number;
  trackWidth: number;
  lineDuration: number;
  baseTimeline: KirakaraTimeline;
  latestTimeline: KirakaraTimeline;
  moved: boolean;
};

type TimingSegment = {
  key: string;
  kind: "mora" | "unit";
  label: string;
  startMs: number;
  endMs: number;
  boundaryIndex: number | null;
};

type MoraBoundaryMarker = {
  segment: TimingSegment;
  boundaryIndex: number;
  leftPercent: number;
  lane: number;
};

const MORA_HANDLE_GAP_PERCENT = 7;
const MORA_HANDLE_TOP_PX = 4;
const MORA_HANDLE_LANE_GAP_PX = 22;
const MORA_SEGMENT_TOP_PX = 76;
const MORA_SEGMENT_HEIGHT_PX = 40;
const MORA_TRACK_BOTTOM_GAP_PX = 12;

function seconds(milliseconds: number): string {
  return (milliseconds / 1000).toFixed(2);
}

function lineTimingSegments(line: KirakaraLine): TimingSegment[] {
  const moraCount = line.units.reduce(
    (count, unit) => count + unit.moras.length,
    0,
  );
  let moraPosition = 0;

  return line.units.flatMap((unit, unitIndex): TimingSegment[] => {
    if (unit.moras.length === 0) {
      if (unit.endMs <= unit.startMs) return [];
      return [{
        key: `unit-${unitIndex}`,
        kind: "unit",
        label: unit.reading || unit.text,
        startMs: unit.startMs,
        endMs: unit.endMs,
        boundaryIndex: null,
      }];
    }

    return unit.moras.map((mora, moraIndex) => {
      const segment: TimingSegment = {
        key: `mora-${unitIndex}-${moraIndex}`,
        kind: "mora",
        label: mora.reading,
        startMs: moraIndex === 0
          ? unit.startMs
          : unit.moras[moraIndex - 1].endMs,
        endMs: moraIndex === unit.moras.length - 1
          ? unit.endMs
          : mora.endMs,
        boundaryIndex: moraPosition < moraCount - 1 ? moraPosition : null,
      };
      moraPosition += 1;
      return segment;
    });
  });
}

function moraBoundaryMarkers(
  segments: TimingSegment[],
  lineStartMs: number,
  lineDurationMs: number,
): MoraBoundaryMarker[] {
  const lastPositionByLane: number[] = [];

  return segments
    .filter(
      (segment) => segment.kind === "mora" && segment.boundaryIndex !== null,
    )
    .map((segment) => {
      const leftPercent = (segment.endMs - lineStartMs) / lineDurationMs * 100;
      let lane = lastPositionByLane.findIndex(
        (lastPosition) => leftPercent - lastPosition >= MORA_HANDLE_GAP_PERCENT,
      );
      if (lane < 0) {
        lane = lastPositionByLane.length;
      }
      lastPositionByLane[lane] = leftPercent;
      return {
        segment,
        boundaryIndex: segment.boundaryIndex as number,
        leftPercent,
        lane,
      };
    });
}

export function KirakaraReviewEditor({
  timeline,
  onChange,
  onSeek,
}: {
  timeline: KirakaraTimeline;
  onChange: (timeline: KirakaraTimeline) => void;
  onSeek: (milliseconds: number) => void;
}) {
  const [lineIndex, setLineIndex] = useState(0);
  const [offset, setOffset] = useState("0.00");
  const [error, setError] = useState<string | null>(null);
  const [activeDrag, setActiveDrag] = useState<TimingDragTarget | null>(null);
  const timelineTrack = useRef<HTMLDivElement | null>(null);
  const timingDrag = useRef<TimingDrag | null>(null);
  const activeLineIndex = timeline.lines[lineIndex] ? lineIndex : 0;
  const line = timeline.lines[activeLineIndex];

  const lineOptions = useMemo(
    () => timeline.lines.map((candidate, index) => ({
      value: index,
      label: `${index + 1}. ${candidate.text}`,
    })),
    [timeline.lines],
  );
  const timingSegments = useMemo(
    () => line ? lineTimingSegments(line) : [],
    [line],
  );
  const boundaryMarkers = useMemo(
    () => line
      ? moraBoundaryMarkers(
          timingSegments,
          line.startMs,
          Math.max(1, line.endMs - line.startMs),
        )
      : [],
    [line, timingSegments],
  );
  const moraHandleLaneCount = boundaryMarkers.reduce(
    (count, marker) => Math.max(count, marker.lane + 1),
    0,
  );
  const moraSegmentTop = Math.max(
    MORA_SEGMENT_TOP_PX,
    MORA_HANDLE_TOP_PX + moraHandleLaneCount * MORA_HANDLE_LANE_GAP_PX + 6,
  );
  const moraTrackHeight = moraSegmentTop
    + MORA_SEGMENT_HEIGHT_PX
    + MORA_TRACK_BOTTOM_GAP_PX;

  function selectLine(index: number) {
    setLineIndex(index);
    setError(null);
    const selected = timeline.lines[index];
    if (selected) onSeek(selected.startMs);
  }

  function changeRange(startMs: number, endMs: number) {
    try {
      onChange(updateLineRange(timeline, activeLineIndex, startMs, endMs));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "时间范围无效");
    }
  }

  function applyOffset() {
    const offsetMs = Math.round(Number(offset) * 1000);
    if (!Number.isFinite(offsetMs)) {
      setError("请输入有效的偏移秒数");
      return;
    }
    onChange(applyTimelineOffset(timeline, offsetMs));
    setOffset("0.00");
    setError(null);
  }

  function startTimingDrag(
    event: ReactPointerEvent<HTMLElement>,
    target: TimingDragTarget,
  ) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const trackWidth = timelineTrack.current?.getBoundingClientRect().width ?? 0;
    if (trackWidth <= 0 || !line) return;

    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    setError(null);
    timingDrag.current = {
      pointerId: event.pointerId,
      lineIndex: activeLineIndex,
      target,
      startClientX: event.clientX,
      trackWidth,
      lineDuration: Math.max(1, line.endMs - line.startMs),
      baseTimeline: timeline,
      latestTimeline: timeline,
      moved: false,
    };
    setActiveDrag(target);
  }

  function moveTimingDrag(event: ReactPointerEvent<HTMLElement>) {
    const drag = timingDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaPixels = event.clientX - drag.startClientX;
    if (!drag.moved && Math.abs(deltaPixels) < 3) return;

    event.preventDefault();
    drag.moved = true;
    const offsetMs = timelineDragOffsetMs(
      deltaPixels,
      drag.trackWidth,
      drag.lineDuration,
    );
    const updated = drag.target.kind === "line-edge"
      ? applyLineEdgeOffset(
          drag.baseTimeline,
          drag.lineIndex,
          drag.target.edge,
          offsetMs,
        )
      : updateMoraBoundary(
          drag.baseTimeline,
          drag.lineIndex,
          drag.target.boundaryIndex,
          drag.target.baseTimeMs + offsetMs,
        );
    drag.latestTimeline = updated;
    onChange(updated);
  }

  function finishTimingDrag(
    event: ReactPointerEvent<HTMLElement>,
    canceled = false,
  ) {
    const drag = timingDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    timingDrag.current = null;
    setActiveDrag(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (drag.moved && !canceled) {
      onSeek(drag.latestTimeline.lines[drag.lineIndex].startMs);
    }
  }

  if (!line) return null;
  const lineDuration = Math.max(1, line.endMs - line.startMs);

  return (
    <section aria-labelledby="timeline-review-heading">
      <h3 id="timeline-review-heading" className="text-base font-bold">
        时间轴与注音检查
      </h3>

      <label
        data-current-line-selector="true"
        className="mt-4 block min-w-0 text-xs font-medium text-muted-foreground"
      >
        当前歌词行
        <select
          className="focus-ring mt-1 block w-full rounded-md border bg-background px-3 py-2.5 text-sm text-foreground"
          value={activeLineIndex}
          onChange={(event) => selectLine(Number(event.target.value))}
        >
          {lineOptions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>

      <div
        data-review-panels="true"
        className="mt-4 grid gap-x-5 gap-y-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)]"
      >
        <section data-timing-panel="true" className="min-w-0 border-t pt-4 lg:h-[32rem] lg:overflow-y-auto lg:overscroll-contain lg:border-r lg:pr-5">
          <div className="flex items-baseline justify-between gap-3">
            <h4 className="text-sm font-bold">设置时间轴</h4>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {seconds(line.startMs)} - {seconds(line.endMs)}
            </span>
          </div>

          <div className="mt-3 px-2">
            <div
              ref={timelineTrack}
              data-mora-timeline="true"
              className="relative rounded-sm border bg-muted/40"
              style={{ height: `${moraTrackHeight}px` }}
              aria-label={`当前歌词行时间轴：${line.text}`}
            >
              {timingSegments.map((segment, index) => {
                const start = Math.max(line.startMs, Math.min(line.endMs, segment.startMs));
                const end = Math.max(start, Math.min(line.endMs, segment.endMs));
                const left = (start - line.startMs) / lineDuration * 100;
                const width = (end - start) / lineDuration * 100;
                return (
                  <div
                    key={segment.key}
                    data-mora-segment={segment.kind === "mora" ? segment.key : undefined}
                    data-unit-segment={segment.kind === "unit" ? segment.key : undefined}
                    className={`absolute flex h-10 min-w-px items-center overflow-hidden rounded-[2px] border text-xs font-semibold ${
                      segment.kind === "unit"
                        ? "border-border bg-background text-muted-foreground"
                        : index % 2 === 0
                          ? "border-primary/45 bg-primary/20 text-foreground"
                          : "border-border bg-card text-foreground"
                    }`}
                    style={{
                      left: `${left}%`,
                      top: `${moraSegmentTop}px`,
                      width: `${width}%`,
                    }}
                    title={`${segment.label} ${seconds(start)} - ${seconds(end)}`}
                  >
                    <span className="block w-full truncate px-1.5 text-center">
                      {segment.label}
                    </span>
                  </div>
                );
              })}

              {boundaryMarkers.map(({ segment, boundaryIndex, leftPercent, lane }) => {
                  const top = MORA_HANDLE_TOP_PX + lane * MORA_HANDLE_LANE_GAP_PX;
                  const stemHeight = moraSegmentTop - top - 20;
                  return (
                    <button
                      key={`boundary-${boundaryIndex}`}
                      type="button"
                      draggable={false}
                      data-mora-boundary={boundaryIndex}
                      data-mora-handle-lane={lane}
                      aria-label={`调整第 ${boundaryIndex + 1} 个 Mora 分界`}
                      title={`调整 ${segment.label} 后的 Mora 分界`}
                      className={`focus-ring absolute z-20 flex size-5 -translate-x-1/2 touch-none select-none cursor-ew-resize items-center justify-center rounded-sm border bg-background shadow-sm ${
                        activeDrag?.kind === "mora-boundary" && activeDrag.boundaryIndex === boundaryIndex
                          ? "border-primary text-primary"
                          : "border-border text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                      }`}
                      style={{ left: `${leftPercent}%`, top: `${top}px` }}
                      onPointerDown={(event) => startTimingDrag(event, {
                        kind: "mora-boundary",
                        boundaryIndex,
                        baseTimeMs: segment.endMs,
                      })}
                      onPointerMove={moveTimingDrag}
                      onPointerUp={finishTimingDrag}
                      onPointerCancel={(event) => finishTimingDrag(event, true)}
                      onLostPointerCapture={(event) => finishTimingDrag(event, true)}
                    >
                      <GripVertical className="size-3.5" />
                      <span
                        className="pointer-events-none absolute left-1/2 top-full w-px -translate-x-1/2 bg-current opacity-35"
                        style={{ height: `${stemHeight}px` }}
                      />
                    </button>
                  );
                })}

              {(["start", "end"] as const).map((edge) => (
                <button
                  key={edge}
                  type="button"
                  draggable={false}
                  data-line-edge={edge}
                  aria-label={`调整当前歌词行的${edge === "start" ? "开始" : "结束"}时间`}
                  title={edge === "start" ? "调整句首" : "调整句尾"}
                  className={`focus-ring absolute z-30 flex h-12 w-5 touch-none select-none cursor-ew-resize items-center justify-center text-primary ${
                    edge === "start" ? "left-0 -translate-x-1/2" : "right-0 translate-x-1/2"
                  }`}
                  style={{ top: `${moraSegmentTop - 4}px` }}
                  onPointerDown={(event) => startTimingDrag(event, { kind: "line-edge", edge })}
                  onPointerMove={moveTimingDrag}
                  onPointerUp={finishTimingDrag}
                  onPointerCancel={(event) => finishTimingDrag(event, true)}
                  onLostPointerCapture={(event) => finishTimingDrag(event, true)}
                >
                  <GripVertical className="size-4" />
                </button>
              ))}
            </div>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-muted-foreground">
              开始时间（秒）
              <input
                type="number"
                min="0"
                step="0.01"
                value={seconds(line.startMs)}
                onChange={(event) => changeRange(Number(event.target.value) * 1000, line.endMs)}
                className="focus-ring mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
              />
            </label>
            <label className="text-xs font-medium text-muted-foreground">
              结束时间（秒）
              <input
                type="number"
                min="0"
                step="0.01"
                value={seconds(line.endMs)}
                onChange={(event) => changeRange(line.startMs, Number(event.target.value) * 1000)}
                className="focus-ring mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
              />
            </label>
            <button
              type="button"
              className="focus-ring inline-flex h-10 items-center justify-center gap-2 rounded-md border px-3 text-sm font-semibold hover:bg-muted sm:col-span-2"
              onClick={() => onSeek(line.startMs)}
            >
              <RotateCcw className="size-4" />
              定位预览
            </button>
          </div>

          <div className="mt-4 grid gap-3 border-t pt-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className="text-xs font-medium text-muted-foreground">
              整体偏移（秒，可为负数）
              <input
                type="number"
                step="0.01"
                value={offset}
                onChange={(event) => setOffset(event.target.value)}
                className="focus-ring mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
              />
            </label>
            <button
              type="button"
              className="focus-ring inline-flex h-10 items-center justify-center gap-2 rounded-md border px-3 text-sm font-semibold hover:bg-muted"
              onClick={applyOffset}
            >
              <TimerReset className="size-4" />
              应用偏移
            </button>
          </div>
        </section>

        <section data-ruby-panel="true" className="flex min-h-0 min-w-0 flex-col border-t pt-4 lg:h-[32rem]">
          <h4 className="text-sm font-bold">设置注音</h4>
          <div
            data-ruby-scroll="true"
            className="mt-3 min-h-0 flex-1 divide-y [scrollbar-gutter:stable] lg:overflow-y-auto lg:overscroll-contain lg:pr-2"
          >
            {line.units.map((unit, unitIndex) => (
              <div key={`${unitIndex}-${unit.text}`} className="grid items-center gap-2 py-3 first:pt-0 sm:grid-cols-[minmax(5rem,0.7fr)_minmax(0,1.3fr)] lg:grid-cols-1">
                <div className="min-w-0">
                  <span className="block break-all text-sm font-semibold">{unit.text}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {seconds(unit.startMs)} - {seconds(unit.endMs)}
                  </span>
                </div>
                <label className="text-xs font-medium text-muted-foreground">
                  注音
                  <input
                    type="text"
                    value={unit.reading}
                    onChange={(event) => onChange(
                      updateUnitReading(timeline, activeLineIndex, unitIndex, event.target.value),
                    )}
                    className="focus-ring mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
                  />
                </label>
              </div>
            ))}
          </div>
        </section>
      </div>

      {error && <p className="mt-3 text-sm text-destructive" role="alert">{error}</p>}
    </section>
  );
}
