"use client";

import { useLayoutEffect, useRef, useState } from "react";

import {
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "@/lib/kirakara-style";
import { inkAwareProgress } from "@/lib/kirakara-progress";
import type {
  KirakaraFrame,
  KirakaraFrameCharacter,
  KirakaraFrameLine,
  KirakaraFrameUnit,
  KirakaraRuby,
} from "@/lib/kirakara-timeline";

const DESIGN_WIDTH = 1280;
const DESIGN_HEIGHT = 720;
const LINE_LEFT = 128;
const MAIN_LETTER_SPACING = 9;
const RUBY_LETTER_SPACING = 5;
const RUBY_OFFSET = 4;
const BEFORE_STROKE = "#000000";
const AFTER_STROKE = "#ffffff";
const strokeCache = new Map<string, string>();
const textMetricsCache = new Map<string, {
  width: number;
  inkLeft: number;
  inkRight: number;
  layoutWidth: number;
}>();
let measurementCanvas: HTMLCanvasElement | null = null;

type RenderGroup = {
  characters: KirakaraFrameCharacter[];
  ruby: KirakaraRuby | null;
};

function clampProgress(progress: number): number {
  return Math.min(1, Math.max(0, progress));
}

function unitCharacters(unit: KirakaraFrameUnit): KirakaraFrameCharacter[] {
  if (unit.characters?.map(({ text }) => text).join("") === unit.text) {
    return unit.characters;
  }
  const characters = [...unit.text];
  const position = clampProgress(unit.progress) * characters.length;
  return characters.map((text, index) => ({
    text,
    progress: clampProgress(position - index),
  }));
}

function splitUnit(unit: KirakaraFrameUnit): RenderGroup[] {
  const characters = unitCharacters(unit);
  const ruby = [...unit.ruby].sort(
    (left, right) => left.startCharacter - right.startCharacter,
  );
  const groups: RenderGroup[] = [];
  let cursor = 0;
  for (const annotation of ruby) {
    if (annotation.startCharacter > cursor) {
      groups.push({
        characters: characters.slice(cursor, annotation.startCharacter),
        ruby: null,
      });
    }
    if (annotation.endCharacter > annotation.startCharacter) {
      groups.push({
        characters: characters.slice(annotation.startCharacter, annotation.endCharacter),
        ruby: annotation,
      });
    }
    cursor = Math.max(cursor, annotation.endCharacter);
  }
  if (cursor < characters.length) {
    groups.push({ characters: characters.slice(cursor), ruby: null });
  }
  return groups.length > 0 ? groups : [{ characters, ruby: null }];
}

function strokeShadow(color: string, width: number): string {
  if (width <= 0) return "none";
  const key = `${color}|${width}`;
  const cached = strokeCache.get(key);
  if (cached) return cached;

  const shadows: string[] = [];
  for (let radius = 1; radius <= width; radius += 0.5) {
    for (let angle = 0; angle < 360; angle += 360 / 32) {
      const radians = angle * Math.PI / 180;
      shadows.push(
        `${(radius * Math.cos(radians)).toFixed(2)}px ${(radius * Math.sin(radians)).toFixed(2)}px 0 ${color}`,
      );
    }
  }
  const value = shadows.join(",");
  strokeCache.set(key, value);
  return value;
}

function clipOverpull(): string {
  return typeof navigator !== "undefined" && /Firefox/i.test(navigator.userAgent)
    ? "-0.5px"
    : "0.5px";
}

function maskPercentage(
  text: string,
  progress: number,
  fontFamily: string,
  fontSize: number,
  fontWeight: number,
  strokeWidth: number,
): number {
  if (typeof document === "undefined") return clampProgress(progress) * 100;

  const key = `${text}|${fontFamily}|${fontSize}|${fontWeight}`;
  let metrics = textMetricsCache.get(key);
  if (!metrics) {
    measurementCanvas ??= document.createElement("canvas");
    const context = measurementCanvas.getContext("2d");
    if (!context) return clampProgress(progress) * 100;
    context.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
    const measured = context.measureText(text);

    const span = document.createElement("span");
    span.textContent = text;
    span.style.position = "fixed";
    span.style.left = "-9999px";
    span.style.visibility = "hidden";
    span.style.whiteSpace = "pre";
    span.style.fontFamily = fontFamily;
    span.style.fontSize = `${fontSize}px`;
    span.style.fontWeight = String(fontWeight);
    span.style.fontKerning = "none";
    span.style.fontVariantLigatures = "none";
    document.body.appendChild(span);
    const layoutWidth = span.scrollWidth;
    span.remove();

    metrics = {
      width: measured.width,
      inkLeft: measured.actualBoundingBoxLeft || 0,
      inkRight: measured.actualBoundingBoxRight || measured.width,
      layoutWidth,
    };
    textMetricsCache.set(key, metrics);
  }

  return inkAwareProgress({
    rawProgress: progress,
    fontSize,
    strokeWidth,
    ...metrics,
  }).percentage;
}

function TextMask({
  text,
  progress,
  fontFamily,
  fontSize,
  fontWeight,
  spacing,
  colorBefore,
  colorAfter,
  strokeBefore,
  strokeAfter,
  strokeWidth,
  ruby = false,
}: {
  text: string;
  progress: number;
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  spacing: number;
  colorBefore: string;
  colorAfter: string;
  strokeBefore: string;
  strokeAfter: string;
  strokeWidth: number;
  ruby?: boolean;
}) {
  const safePad = strokeWidth > 0 ? Math.max(1, strokeWidth) : 0;
  const percentage = maskPercentage(
    text,
    progress,
    fontFamily,
    fontSize,
    fontWeight,
    safePad,
  );
  const leftClip = percentage <= 0 ? "100%" : `-${safePad}px`;
  const rightClip = 100 - percentage;
  const baseStyle = {
    display: "inline-block",
    padding: `${safePad}px`,
    fontFamily,
    fontSize: `${fontSize}px`,
    fontWeight,
    fontKerning: "none" as const,
    fontVariantLigatures: "none",
    fontOpticalSizing: "none",
    lineHeight: ruby ? 1.1 : 1.2,
    whiteSpace: "pre" as const,
  };

  return (
    <span
      data-kirakara-character={ruby ? undefined : text}
      data-kirakara-ruby-character={ruby ? text : undefined}
      style={{
        position: "relative",
        display: "inline-block",
        flexShrink: 0,
        margin: `-${safePad}px`,
        marginRight: `${spacing - safePad}px`,
        verticalAlign: "bottom",
      }}
    >
      <span
        style={{
          ...baseStyle,
          color: colorBefore,
          textShadow: strokeShadow(strokeBefore, strokeWidth),
        }}
      >
        {text}
      </span>
      <span
        style={{
          ...baseStyle,
          position: "absolute",
          left: 0,
          top: 0,
          color: colorAfter,
          textShadow: strokeShadow(strokeAfter, strokeWidth),
          clipPath: `inset(-50% calc(${rightClip}% + ${clipOverpull()}) -50% ${leftClip})`,
        }}
      >
        {text}
      </span>
    </span>
  );
}

function LyricGroup({ group, style, last }: {
  group: RenderGroup;
  style: KirakaraStyle;
  last: boolean;
}) {
  const groupProgress = group.characters.length > 0
    ? group.characters.reduce((total, character) => total + character.progress, 0)
      / group.characters.length
    : 0;
  const rubyCharacters = group.ruby ? [...group.ruby.text] : [];
  const rubyPosition = groupProgress * rubyCharacters.length;

  return (
    <span
      style={{
        position: "relative",
        display: "inline-grid",
        alignItems: "end",
        justifyItems: "center",
        marginRight: last ? 0 : `${MAIN_LETTER_SPACING}px`,
      }}
    >
      {group.ruby && (
        <span
          aria-hidden="true"
          data-kirakara-ruby-sizer="true"
          style={{
            gridArea: "1 / 1",
            height: 0,
            visibility: "hidden",
            whiteSpace: "nowrap",
            fontFamily: style.fontFamily,
            fontSize: `${style.rubySize}px`,
            lineHeight: 0,
            display: "inline-flex",
          }}
        >
          {rubyCharacters.map((text, index) => (
            <span
              key={`${index}-${text}`}
              style={{
                display: "inline-block",
                marginRight: index === rubyCharacters.length - 1
                  ? 0
                  : `${RUBY_LETTER_SPACING}px`,
              }}
            >
              {text}
            </span>
          ))}
        </span>
      )}
      <span
        style={{
          gridArea: "1 / 1",
          display: "inline-flex",
          alignItems: "flex-end",
        }}
      >
        {group.characters.map((character, index) => (
          <TextMask
            key={`${index}-${character.text}`}
            text={character.text}
            progress={character.progress}
            fontFamily={style.fontFamily}
            fontSize={style.fontSize}
            fontWeight={700}
            spacing={index === group.characters.length - 1 ? 0 : MAIN_LETTER_SPACING}
            colorBefore={style.colorBefore}
            colorAfter={style.colorAfter}
            strokeBefore={BEFORE_STROKE}
            strokeAfter={AFTER_STROKE}
            strokeWidth={style.strokeWidth}
          />
        ))}
      </span>
      {group.ruby && (
        <span
          style={{
            position: "absolute",
            bottom: `calc(100% + ${RUBY_OFFSET}px)`,
            left: "50%",
            display: "inline-flex",
            transform: "translateX(-50%)",
            whiteSpace: "nowrap",
          }}
        >
          {rubyCharacters.map((text, index) => (
            <TextMask
              key={`${index}-${text}`}
              text={text}
              progress={clampProgress(rubyPosition - index)}
              fontFamily={style.fontFamily}
              fontSize={style.rubySize}
              fontWeight={400}
              spacing={index === rubyCharacters.length - 1 ? 0 : RUBY_LETTER_SPACING}
              colorBefore={style.colorBefore}
              colorAfter={style.colorAfter}
              strokeBefore={BEFORE_STROKE}
              strokeAfter={AFTER_STROKE}
              strokeWidth={Math.max(2, style.strokeWidth * 0.8)}
              ruby
            />
          ))}
        </span>
      )}
    </span>
  );
}

function LyricLine({ line, style }: { line: KirakaraFrameLine; style: KirakaraStyle }) {
  const groups = line.units.flatMap(splitUnit);
  const upper = line.slot === "upper";
  return (
    <div
      data-kirakara-line={line.slot}
      style={{
        position: "absolute",
        top: `${upper ? style.upperY : style.lowerY}px`,
        ...(upper ? { left: `${LINE_LEFT}px` } : { right: `${LINE_LEFT}px` }),
        display: "flex",
        alignItems: "flex-end",
        whiteSpace: "nowrap",
      }}
    >
      {groups.map((group, index) => (
        <LyricGroup
          key={index}
          group={group}
          style={style}
          last={index === groups.length - 1}
        />
      ))}
    </div>
  );
}

export function KirakaraDomFrame({
  frame,
  style: rawStyle,
}: {
  frame: KirakaraFrame | null;
  style: KirakaraStyle;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ scale: 1, left: 0, top: 0 });
  const style = normalizeKirakaraStyle(rawStyle);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const resize = () => {
      const scale = Math.min(
        host.clientWidth / DESIGN_WIDTH,
        host.clientHeight / DESIGN_HEIGHT,
      );
      setViewport({
        scale,
        left: (host.clientWidth - DESIGN_WIDTH * scale) / 2,
        top: (host.clientHeight - DESIGN_HEIGHT * scale) / 2,
      });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={hostRef}
      data-kirakara-dom-preview="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
      aria-hidden="true"
    >
      <div
        style={{
          position: "absolute",
          left: viewport.left,
          top: viewport.top,
          width: DESIGN_WIDTH,
          height: DESIGN_HEIGHT,
          overflow: "visible",
          transform: `scale(${viewport.scale})`,
          transformOrigin: "left top",
        }}
      >
        {frame?.lines.map((line) => (
          <LyricLine key={`${line.slot}-${line.text}`} line={line} style={style} />
        ))}
      </div>
    </div>
  );
}
