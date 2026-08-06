"use client";

import { RotateCcw } from "lucide-react";

import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "@/lib/kirakara-style";

const FONT_OPTIONS = [
  { label: "Noto Sans JP", value: DEFAULT_KIRAKARA_STYLE.fontFamily },
  { label: "Yu Gothic", value: '"Yu Gothic", "Noto Sans JP", sans-serif' },
  { label: "Microsoft YaHei", value: '"Microsoft YaHei", "Noto Sans JP", sans-serif' },
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
    <section className="mt-5 border-t pt-5" aria-labelledby="kirakara-style-heading">
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

      <div className="mt-4 grid gap-5 sm:grid-cols-2">
        <label className="grid gap-2 text-sm font-medium">
          字体
          <select
            value={style.fontFamily}
            onChange={(event) => update({ fontFamily: event.target.value })}
            className="focus-ring h-10 rounded-md border bg-background px-3"
          >
            {FONT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <RangeField label="描边" value={style.strokeWidth} min={2} max={8} onChange={(strokeWidth) => update({ strokeWidth })} />
        <RangeField label="主字大小" value={style.fontSize} min={48} max={80} onChange={(fontSize) => update({ fontSize })} />
        <RangeField label="注音大小" value={style.rubySize} min={18} max={38} onChange={(rubySize) => update({ rubySize })} />
        <RangeField label="上行位置" value={style.upperY} min={320} max={560} onChange={(upperY) => update({ upperY })} />
        <RangeField label="下行位置" value={style.lowerY} min={440} max={680} onChange={(lowerY) => update({ lowerY })} />
        <label className="flex items-center justify-between gap-3 text-sm font-medium">
          未唱颜色
          <input type="color" value={style.colorBefore} onChange={(event) => update({ colorBefore: event.target.value })} className="h-10 w-14 cursor-pointer rounded-md border bg-background p-1" />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm font-medium">
          已唱颜色
          <input type="color" value={style.colorAfter} onChange={(event) => update({ colorAfter: event.target.value })} className="h-10 w-14 cursor-pointer rounded-md border bg-background p-1" />
        </label>
      </div>
    </section>
  );
}
