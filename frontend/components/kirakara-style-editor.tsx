"use client";

import { ChevronDown, RotateCcw } from "lucide-react";

import {
  DEFAULT_KIRAKARA_STYLE,
  KIRAKARA_STYLE_PRESETS,
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
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid min-w-0 gap-2 text-sm font-medium">
      <span className="flex items-center justify-between gap-3 whitespace-nowrap">
        {label}
        <span className="tabular-nums text-muted-foreground">{value}{unit}</span>
      </span>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-2 w-full cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
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

  const selectedPreset = KIRAKARA_STYLE_PRESETS.find(
    (preset) => JSON.stringify(preset.style) === JSON.stringify(style),
  )?.id ?? "custom";

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

      <div className="mt-3 grid min-w-0 gap-4">
        <label className="grid min-w-0 gap-2 text-sm font-medium">
          样式预设
          <select
            aria-label="样式预设"
            value={selectedPreset}
            onChange={(event) => {
              const preset = KIRAKARA_STYLE_PRESETS.find(
                (candidate) => candidate.id === event.target.value,
              );
              if (preset) onChange(preset.style);
            }}
            className="focus-ring h-10 min-w-0 rounded-md border bg-background px-3"
          >
            <option value="custom" disabled>自定义</option>
            {KIRAKARA_STYLE_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>{preset.label}</option>
            ))}
          </select>
        </label>
        <label
          className="grid min-w-0 gap-2 text-sm font-medium"
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
        <fieldset className="grid min-w-0 gap-3 rounded-lg border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">主字</legend>
          <label className="grid min-w-0 gap-2 text-sm font-medium">
            字体粗细
            <select
              aria-label="字体粗细"
              value={style.fontBold ? "bold" : "normal"}
              onChange={(event) => update({ fontBold: event.target.value === "bold" })}
              className="focus-ring h-9 min-w-0 rounded-md border bg-background px-3"
            >
              <option value="normal">常规</option>
              <option value="bold">粗体</option>
            </select>
          </label>
          <div className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-3">
            <RangeField label="主字大小" value={style.fontSize} min={24} max={120} onChange={(fontSize) => update({ fontSize })} />
            <RangeField label="主字字间距" value={style.letterSpacing} min={-4} max={32} onChange={(letterSpacing) => update({ letterSpacing })} />
          </div>
        </fieldset>

        <fieldset className="grid min-w-0 gap-3 rounded-lg border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">假名注音</legend>
          <div className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-3">
            <RangeField label="注音大小" value={style.rubySize} min={10} max={60} onChange={(rubySize) => update({ rubySize })} />
            <RangeField label="注音字间距" value={style.rubyLetterSpacing} min={-2} max={20} onChange={(rubyLetterSpacing) => update({ rubyLetterSpacing })} />
            <RangeField label="注音偏移" value={style.rubyOffset} min={0} max={32} onChange={(rubyOffset) => update({ rubyOffset })} />
          </div>
        </fieldset>

        <fieldset className="grid min-w-0 gap-3 rounded-lg border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">罗马音注音</legend>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              aria-label="跟随假名注音"
              checked={style.romajiFollowRuby}
              onChange={(event) => update(event.target.checked
                ? { romajiFollowRuby: true }
                : {
                    romajiFollowRuby: false,
                    romajiSize: style.rubySize,
                    romajiLetterSpacing: style.rubyLetterSpacing,
                    romajiOffset: style.rubyOffset,
                  })}
            />
            跟随假名注音
          </label>
          <div className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-3">
            <RangeField
              label="罗马音大小"
              value={style.romajiFollowRuby ? style.rubySize : style.romajiSize}
              min={10}
              max={60}
              disabled={style.romajiFollowRuby}
              onChange={(romajiSize) => update({ romajiSize })}
            />
            <RangeField
              label="罗马音音间距"
              value={style.romajiFollowRuby
                ? style.rubyLetterSpacing
                : style.romajiLetterSpacing}
              min={-2}
              max={20}
              disabled={style.romajiFollowRuby}
              onChange={(romajiLetterSpacing) => update({ romajiLetterSpacing })}
            />
            <RangeField
              label="罗马音偏移"
              value={style.romajiFollowRuby ? style.rubyOffset : style.romajiOffset}
              min={0}
              max={32}
              disabled={style.romajiFollowRuby}
              onChange={(romajiOffset) => update({ romajiOffset })}
            />
          </div>
        </fieldset>

        <fieldset className="grid min-w-0 gap-3 rounded-lg border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">颜色与效果</legend>
          <div className="grid min-w-0 grid-cols-2 gap-3">
            <ColorField label="未唱" value={style.colorBefore} onChange={(colorBefore) => update({ colorBefore })} />
            <ColorField label="已唱" value={style.colorAfter} onChange={(colorAfter) => update({ colorAfter })} />
            <ColorField label="未唱描边" value={style.strokeColorBefore} onChange={(strokeColorBefore) => update({ strokeColorBefore })} />
            <ColorField label="已唱描边" value={style.strokeColorAfter} onChange={(strokeColorAfter) => update({ strokeColorAfter })} />
          </div>
          <div className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-3">
            <RangeField label="描边粗细" value={style.strokeWidth} min={0} max={12} onChange={(strokeWidth) => update({ strokeWidth })} />
            <RangeField label="阴影深度" value={style.shadowDepth} min={0} max={12} onChange={(shadowDepth) => update({ shadowDepth })} />
          </div>
          <ColorField label="阴影颜色" value={style.shadowColor} onChange={(shadowColor) => update({ shadowColor })} />
        </fieldset>

        <fieldset className="grid min-w-0 gap-3 rounded-lg border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">画面布局</legend>
          <div className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-3">
            <RangeField label="横向安全边距" value={style.horizontalMargin} min={0} max={320} onChange={(horizontalMargin) => update({ horizontalMargin })} />
            <RangeField label="上行位置" value={style.upperY} min={120} max={600} onChange={(upperY) => update({ upperY })} />
            <RangeField label="下行位置" value={style.lowerY} min={240} max={700} onChange={(lowerY) => update({ lowerY })} />
          </div>
        </fieldset>
      </div>
    </section>
  );
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1 whitespace-nowrap text-xs font-medium">
      {label}
      <input
        type="color"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full cursor-pointer rounded-md border bg-background p-1"
      />
    </label>
  );
}
