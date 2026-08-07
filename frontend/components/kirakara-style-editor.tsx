"use client";

import { ChevronDown, RotateCcw } from "lucide-react";

import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "@/lib/kirakara-style";

const FONT_OPTIONS = [
  { label: "Noto Sans JP", value: "'Noto Sans JP', sans-serif" },
  { label: "Noto Sans CJK JP", value: "'Noto Sans CJK JP', sans-serif" },
  { label: "Yu Gothic", value: "'Yu Gothic', sans-serif" },
  { label: "Yu Mincho", value: "'Yu Mincho', serif" },
  { label: "Meiryo", value: "Meiryo, sans-serif" },
  { label: "MS Gothic", value: "'MS Gothic', monospace" },
  { label: "系统默认", value: "system-ui, sans-serif" },
];

function RangeField({
  label,
  value,
  min,
  max,
  unit = "px",
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid gap-2 text-sm font-medium">
      <span className="flex items-center justify-between gap-3">
        {label}
        <span className="tabular-nums text-muted-foreground">{value}{unit}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-2 w-full cursor-pointer accent-primary"
      />
    </label>
  );
}

export function KirakaraStyleEditor({
  style,
  onChange,
}: {
  style: KirakaraStyle;
  onChange: (style: KirakaraStyle) => void;
}) {
  function update(patch: Partial<KirakaraStyle>) {
    onChange(normalizeKirakaraStyle({ ...style, ...patch }));
  }

  return (
    <section
      aria-labelledby="kirakara-style-heading"
      data-kirakara-style-layout="responsive"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 id="kirakara-style-heading" className="text-base font-bold">字幕样式</h3>
        <button
          type="button"
          title="恢复 Kirakara 默认样式"
          aria-label="恢复 Kirakara 默认样式"
          onClick={() => onChange(DEFAULT_KIRAKARA_STYLE)}
          className="focus-ring inline-flex size-9 items-center justify-center rounded-md border text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <RotateCcw className="size-4" />
        </button>
      </div>

      <div className="mt-3 grid gap-x-5 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
        <label
          className="grid gap-2 text-sm font-medium sm:col-span-2"
          data-kirakara-font-control="kirakara"
        >
          字体
          <span className="focus-within:focus-ring flex h-10 min-w-0 items-stretch overflow-hidden rounded-md border bg-background">
            <input
              type="text"
              value={style.fontFamily}
              onChange={(event) =>
                onChange({ ...style, fontFamily: event.target.value })
              }
              placeholder="输入字体名"
              autoComplete="off"
              className="min-w-0 flex-1 bg-transparent px-3 outline-none"
            />
            <span className="relative w-10 shrink-0 border-l">
              <select
                aria-label="选择字体预设"
                value={FONT_OPTIONS.some((option) => option.value === style.fontFamily)
                  ? style.fontFamily
                  : ""}
                onChange={(event) => {
                  if (event.target.value) {
                    onChange({ ...style, fontFamily: event.target.value });
                  }
                }}
                className="absolute inset-0 size-full cursor-pointer opacity-0"
              >
                <option value="" disabled>选择字体预设</option>
                {FONT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute inset-0 m-auto size-4 text-muted-foreground" />
            </span>
          </span>
        </label>
        <RangeField label="描边" value={style.strokeWidth} min={2} max={8} onChange={(strokeWidth) => update({ strokeWidth })} />
        <RangeField label="主字大小" value={style.fontSize} min={48} max={80} onChange={(fontSize) => update({ fontSize })} />
        <RangeField label="注音大小" value={style.rubySize} min={18} max={38} onChange={(rubySize) => update({ rubySize })} />
        <RangeField label="上行位置" value={style.upperY} min={320} max={560} onChange={(upperY) => update({ upperY })} />
        <RangeField label="下行位置" value={style.lowerY} min={440} max={680} onChange={(lowerY) => update({ lowerY })} />
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1 text-xs font-medium">
            未唱颜色
            <input type="color" value={style.colorBefore} onChange={(event) => update({ colorBefore: event.target.value })} className="h-9 w-full cursor-pointer rounded-md border bg-background p-1" />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            已唱颜色
            <input type="color" value={style.colorAfter} onChange={(event) => update({ colorAfter: event.target.value })} className="h-9 w-full cursor-pointer rounded-md border bg-background p-1" />
          </label>
        </div>
      </div>
    </section>
  );
}
