import type { KirakaraFrame, KirakaraFrameLine, KirakaraRuby } from "./kirakara-timeline";
import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "./kirakara-style";

export type KirakaraCanvasContext = {
  canvas: Pick<HTMLCanvasElement, "width" | "height">;
  clearRect(x: number, y: number, width: number, height: number): void;
  fillText(text: string, x: number, y: number): void;
  strokeText(text: string, x: number, y: number): void;
  measureText(text: string): { width: number };
  save(): void;
  restore(): void;
  beginPath(): void;
  rect(x: number, y: number, width: number, height: number): void;
  clip(): void;
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  lineWidth: number;
  font: string;
  textBaseline: CanvasTextBaseline;
};

type LayoutGroup = {
  text: string;
  ruby: KirakaraRuby | null;
  progress: number;
  baseWidth: number;
  rubyWidth: number;
  effectiveWidth: number;
  isolatePad: number;
  x: number;
};

const BEFORE_STROKE = "#000000";
const AFTER_STROKE = "#ffffff";

function drawText(context: KirakaraCanvasContext, text: string, x: number, y: number, fill: string, stroke: string): void {
  context.strokeStyle = stroke;
  context.fillStyle = fill;
  context.strokeText(text, x, y);
  context.fillText(text, x, y);
}

function splitUnit(text: string, ruby: KirakaraRuby[], progress: number) {
  const characters = [...text];
  const sorted = [...ruby].sort((left, right) => left.startCharacter - right.startCharacter);
  const groups: Array<{ text: string; ruby: KirakaraRuby | null; progress: number }> = [];
  let cursor = 0;
  for (const annotation of sorted) {
    if (annotation.startCharacter > cursor) {
      groups.push({ text: characters.slice(cursor, annotation.startCharacter).join(""), ruby: null, progress });
    }
    if (annotation.endCharacter > annotation.startCharacter) {
      groups.push({
        text: characters.slice(annotation.startCharacter, annotation.endCharacter).join(""),
        ruby: annotation,
        progress,
      });
    }
    cursor = Math.max(cursor, annotation.endCharacter);
  }
  if (cursor < characters.length) {
    groups.push({ text: characters.slice(cursor).join(""), ruby: null, progress });
  }
  return groups.length > 0 ? groups : [{ text, ruby: null, progress }];
}

function layoutLine(
  context: KirakaraCanvasContext,
  line: KirakaraFrameLine,
  style: KirakaraStyle,
  scaleX: number,
  scaleY: number,
): LayoutGroup[] {
  const mainFontSize = style.fontSize * scaleY;
  const rubyFontSize = style.rubySize * scaleY;
  const mainFont = `700 ${mainFontSize}px ${style.fontFamily}`;
  const rubyFont = `400 ${rubyFontSize}px ${style.fontFamily}`;
  const sourceGroups = line.units.flatMap((unit) => splitUnit(unit.text, unit.ruby, unit.progress));

  const groups = sourceGroups.map((group): LayoutGroup => {
    context.font = mainFont;
    const baseWidth = context.measureText(group.text).width;
    context.font = rubyFont;
    const rubyWidth = group.ruby ? context.measureText(group.ruby.text).width : 0;
    const effectiveWidth = Math.max(baseWidth, rubyWidth);
    return {
      ...group,
      baseWidth,
      rubyWidth,
      effectiveWidth,
      isolatePad: (effectiveWidth - baseWidth) / 2,
      x: 0,
    };
  });

  const totalWidth = groups.reduce((total, group) => total + group.effectiveWidth, 0);
  const left = 128 * scaleX;
  let cursorX = line.slot === "upper" ? left : context.canvas.width - left - totalWidth;
  for (const group of groups) {
    group.x = cursorX;
    cursorX += group.effectiveWidth;
  }
  return groups;
}

function drawLine(
  context: KirakaraCanvasContext,
  line: KirakaraFrameLine,
  style: KirakaraStyle,
  scaleX: number,
  scaleY: number,
): void {
  const fontSize = style.fontSize * scaleY;
  const rubyFontSize = style.rubySize * scaleY;
  const mainFont = `700 ${fontSize}px ${style.fontFamily}`;
  const rubyFont = `400 ${rubyFontSize}px ${style.fontFamily}`;
  const groups = layoutLine(context, line, style, scaleX, scaleY);
  const baseline = (line.slot === "upper" ? style.upperY : style.lowerY) * scaleY;
  const rubyBaseline = baseline - fontSize * 1.05;

  context.textBaseline = "alphabetic";
  for (const group of groups) {
    const baseX = group.x + group.isolatePad;
    context.font = mainFont;
    context.lineWidth = style.strokeWidth * scaleY;
    drawText(context, group.text, baseX, baseline, style.colorBefore, BEFORE_STROKE);
    if (group.progress > 0) {
      context.save();
      context.beginPath();
      context.rect(baseX, baseline - fontSize * 1.25, group.baseWidth * group.progress, fontSize * 1.75);
      context.clip();
      drawText(context, group.text, baseX, baseline, style.colorAfter, AFTER_STROKE);
      context.restore();
    }

    if (!group.ruby) continue;
    const rubyX = group.x + (group.effectiveWidth - group.rubyWidth) / 2;
    context.font = rubyFont;
    context.lineWidth = Math.max(2, style.strokeWidth * 0.8 * scaleY);
    drawText(context, group.ruby.text, rubyX, rubyBaseline, style.colorBefore, BEFORE_STROKE);
    if (group.progress > 0) {
      context.save();
      context.beginPath();
      context.rect(rubyX, rubyBaseline - rubyFontSize, group.rubyWidth * group.progress, rubyFontSize * 1.5);
      context.clip();
      drawText(context, group.ruby.text, rubyX, rubyBaseline, style.colorAfter, AFTER_STROKE);
      context.restore();
    }
  }
}

export function drawKirakaraFrame(
  context: KirakaraCanvasContext,
  frame: KirakaraFrame | null,
  options: { clear?: boolean; style?: KirakaraStyle } = {},
): void {
  const { width, height } = context.canvas;
  if (options.clear !== false) context.clearRect(0, 0, width, height);
  if (!frame) return;

  const style = normalizeKirakaraStyle(options.style ?? DEFAULT_KIRAKARA_STYLE);
  const scaleX = width / 1280;
  const scaleY = height / 720;
  for (const line of frame.lines) drawLine(context, line, style, scaleX, scaleY);
}
