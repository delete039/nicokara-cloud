"use client";

import { RotateCcw, TimerReset } from "lucide-react";
import { useMemo, useState } from "react";

import {
  applyTimelineOffset,
  updateLineRange,
  updateUnitReading,
} from "@/lib/kirakara-review";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";

function seconds(milliseconds: number): string {
  return (milliseconds / 1000).toFixed(2);
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
  const activeLineIndex = timeline.lines[lineIndex] ? lineIndex : 0;
  const line = timeline.lines[activeLineIndex];
  const visualDuration = Math.max(timeline.durationMs, 1);

  const lineOptions = useMemo(
    () => timeline.lines.map((candidate, index) => ({
      value: index,
      label: `${index + 1}. ${candidate.text}`,
    })),
    [timeline.lines],
  );

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

  if (!line) return null;

  return (
    <section aria-labelledby="timeline-review-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 id="timeline-review-heading" className="text-base font-bold">
            时间轴与注音检查
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            修改会立即反映在上方预览，并用于本地导出或云端渲染。
          </p>
        </div>
        <label className="min-w-0 text-xs font-medium text-muted-foreground">
          当前歌词行
          <select
            className="focus-ring mt-1 block max-w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
            value={activeLineIndex}
            onChange={(event) => selectLine(Number(event.target.value))}
          >
            {lineOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-4 overflow-x-auto pb-2" aria-label="歌词时间轴">
        <div className="relative h-12 min-w-[36rem] rounded-md bg-muted">
          {timeline.lines.map((candidate, index) => {
            const left = candidate.startMs / visualDuration * 100;
            const width = Math.max(1.5, (candidate.endMs - candidate.startMs) / visualDuration * 100);
            return (
              <button
                key={`${index}-${candidate.text}`}
                type="button"
                className={`focus-ring absolute inset-y-1 overflow-hidden rounded-sm border px-2 text-left text-xs ${
                  index === activeLineIndex
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-foreground hover:bg-card"
                }`}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`${seconds(candidate.startMs)} - ${seconds(candidate.endMs)} ${candidate.text}`}
                onClick={() => selectLine(index)}
              >
                <span className="block truncate">{candidate.text}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
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
          className="focus-ring inline-flex h-10 items-center justify-center gap-2 self-end rounded-md border px-3 text-sm font-semibold hover:bg-muted"
          onClick={() => onSeek(line.startMs)}
        >
          <RotateCcw className="size-4" />
          定位预览
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3 border-y py-4">
        <label className="text-xs font-medium text-muted-foreground">
          整体偏移（秒，可为负数）
          <input
            type="number"
            step="0.01"
            value={offset}
            onChange={(event) => setOffset(event.target.value)}
            className="focus-ring mt-1 block w-40 rounded-md border bg-background px-3 py-2 text-sm text-foreground"
          />
        </label>
        <button
          type="button"
          className="focus-ring inline-flex h-10 items-center gap-2 rounded-md border px-3 text-sm font-semibold hover:bg-muted"
          onClick={applyOffset}
        >
          <TimerReset className="size-4" />
          应用偏移
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {line.units.map((unit, unitIndex) => (
          <div key={`${unitIndex}-${unit.text}`} className="grid items-center gap-2 sm:grid-cols-[minmax(5rem,0.7fr)_minmax(0,1.3fr)]">
            <div className="min-w-0">
              <span className="block break-all text-sm font-semibold">{unit.text}</span>
              <span className="text-xs text-muted-foreground">
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

      {error && <p className="mt-3 text-sm text-destructive" role="alert">{error}</p>}
    </section>
  );
}
