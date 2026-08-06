import type {
  KirakaraFrame,
  KirakaraFrameCharacter,
  KirakaraFrameLine,
  KirakaraFrameUnit,
  KirakaraRuby,
} from "./kirakara-timeline";
import {
  DEFAULT_KIRAKARA_STYLE,
  normalizeKirakaraStyle,
  type KirakaraStyle,
} from "./kirakara-style";
import { inkAwareProgress } from "./kirakara-progress";

export type KirakaraCanvasContext = {
  canvas: Pick<HTMLCanvasElement, "width" | "height">;
  clearRect(x: number, y: number, width: number, height: number): void;
  fillText(text: string, x: number, y: number): void;
  strokeText(text: string, x: number, y: number): void;
  measureText(text: string): {
    width: number;
    actualBoundingBoxLeft?: number;
    actualBoundingBoxRight?: number;
  };
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
  characters: Array<KirakaraFrameCharacter & { width: number; x: number }>;
  ruby: KirakaraRuby | null;
  baseWidth: number;
  rubyWidth: number;
  effectiveWidth: number;
  isolatePad: number;
  x: number;
};

const BEFORE_STROKE = "#000000";
const AFTER_STROKE = "#ffffff";
const MAIN_LETTER_SPACING = 9;
const RUBY_LETTER_SPACING = 5;
const RUBY_OFFSET = 4;
const MAIN_LINE_HEIGHT = 1.2;
const RUBY_LINE_HEIGHT = 1.1;
const baselineCache = new Map<string, number>();

function drawText(context: KirakaraCanvasContext, text: string, x: number, y: number, fill: string, stroke: string): void {
  context.strokeStyle = stroke;
  context.fillStyle = fill;
  context.strokeText(text, x, y);
  context.fillText(text, x, y);
}

function fallbackCharacters(unit: KirakaraFrameUnit): KirakaraFrameCharacter[] {
  const text = [...unit.text];
  const position = Math.min(1, Math.max(0, unit.progress)) * text.length;
  return text.map((character, index) => ({
    text: character,
    progress: Math.min(1, Math.max(0, position - index)),
  }));
}

function unitCharacters(unit: KirakaraFrameUnit): KirakaraFrameCharacter[] {
  const source = unit.characters;
  if (source && source.map(({ text }) => text).join("") === unit.text) return source;
  return fallbackCharacters(unit);
}

function splitUnit(unit: KirakaraFrameUnit) {
  const characters = unitCharacters(unit);
  const sorted = [...unit.ruby].sort(
    (left, right) => left.startCharacter - right.startCharacter,
  );
  const groups: Array<{
    characters: KirakaraFrameCharacter[];
    ruby: KirakaraRuby | null;
  }> = [];
  let cursor = 0;
  for (const annotation of sorted) {
    if (annotation.startCharacter > cursor) {
      groups.push({ characters: characters.slice(cursor, annotation.startCharacter), ruby: null });
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

function measureBaselineOffset(
  fontSize: number,
  fontFamily: string,
  fontWeight: "normal" | "700",
  lineHeight: number,
): number {
  const cacheKey = `${fontSize}|${fontFamily}|${fontWeight}|${lineHeight}`;
  const cached = baselineCache.get(cacheKey);
  if (cached !== undefined) return cached;

  if (typeof document !== "undefined" && document.body) {
    const line = document.createElement("span");
    const marker = document.createElement("span");
    line.textContent = "国";
    line.style.position = "fixed";
    line.style.left = "-9999px";
    line.style.visibility = "hidden";
    line.style.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
    line.style.lineHeight = String(lineHeight);
    marker.style.display = "inline-block";
    marker.style.width = "1px";
    marker.style.height = "0";
    marker.style.verticalAlign = "baseline";
    line.appendChild(marker);
    document.body.appendChild(line);
    const offset = marker.getBoundingClientRect().top - line.getBoundingClientRect().top;
    line.remove();
    if (Number.isFinite(offset) && offset > 0) {
      baselineCache.set(cacheKey, offset);
      return offset;
    }
  }

  const fallback = fontSize * 0.88 + fontSize * (lineHeight - 1) / 2;
  baselineCache.set(cacheKey, fallback);
  return fallback;
}

function clipCharacter(
  context: KirakaraCanvasContext,
  text: string,
  x: number,
  baseline: number,
  fontSize: number,
  progress: number,
  strokeWidth: number,
): void {
  const metrics = context.measureText(text);
  const inkLeft = metrics.actualBoundingBoxLeft ?? 0;
  const inkRight = metrics.actualBoundingBoxRight ?? metrics.width;
  const mask = inkAwareProgress({
    rawProgress: progress,
    fontSize,
    strokeWidth,
    width: metrics.width,
    inkLeft,
    inkRight,
    layoutWidth: fontSize,
  });

  context.rect(
    x - fontSize,
    baseline - fontSize * 2.5,
    mask.canvasWidth,
    fontSize * 4,
  );
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
  const sourceGroups = line.units.flatMap((unit) => splitUnit(unit));

  const groups = sourceGroups.map((group): LayoutGroup => {
    context.font = mainFont;
    const characters = group.characters.map((character) => ({
      ...character,
      width: context.measureText(character.text).width,
      x: 0,
    }));
    const baseWidth = characters.reduce((width, character) => width + character.width, 0)
      + Math.max(0, characters.length - 1) * MAIN_LETTER_SPACING * scaleX;
    context.font = rubyFont;
    const rubyCharacters = group.ruby ? [...group.ruby.text] : [];
    const rubyWidth = rubyCharacters.reduce(
      (width, character) => width + context.measureText(character).width,
      0,
    ) + Math.max(0, rubyCharacters.length - 1) * RUBY_LETTER_SPACING * scaleX;
    const effectiveWidth = Math.max(baseWidth, rubyWidth);
    return {
      ...group,
      characters,
      baseWidth,
      rubyWidth,
      effectiveWidth,
      isolatePad: (effectiveWidth - baseWidth) / 2,
      x: 0,
    };
  });

  const groupSpacing = MAIN_LETTER_SPACING * scaleX;
  const totalWidth = groups.reduce((total, group) => total + group.effectiveWidth, 0)
    + Math.max(0, groups.length - 1) * groupSpacing;
  const left = 128 * scaleX;
  let cursorX = line.slot === "upper" ? left : context.canvas.width - left - totalWidth;
  for (const group of groups) {
    group.x = cursorX;
    let characterX = cursorX + group.isolatePad;
    for (const character of group.characters) {
      character.x = characterX;
      characterX += character.width + MAIN_LETTER_SPACING * scaleX;
    }
    cursorX += group.effectiveWidth + groupSpacing;
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
  const lineTop = (line.slot === "upper" ? style.upperY : style.lowerY) * scaleY;
  const baseline = lineTop + measureBaselineOffset(
    fontSize,
    style.fontFamily,
    "700",
    MAIN_LINE_HEIGHT,
  );
  const rubyBaselineOffset = measureBaselineOffset(
    rubyFontSize,
    style.fontFamily,
    "normal",
    RUBY_LINE_HEIGHT,
  );
  const rubyBaseline = lineTop
    - RUBY_OFFSET * scaleY
    - (rubyFontSize * RUBY_LINE_HEIGHT - rubyBaselineOffset);

  context.textBaseline = "alphabetic";
  for (const group of groups) {
    context.font = mainFont;
    const mainStrokeWidth = style.strokeWidth * scaleY;
    context.lineWidth = mainStrokeWidth * 2.2;
    for (const character of group.characters) {
      drawText(context, character.text, character.x, baseline, style.colorBefore, BEFORE_STROKE);
      context.save();
      context.beginPath();
      clipCharacter(
        context,
        character.text,
        character.x,
        baseline,
        fontSize,
        character.progress,
        mainStrokeWidth,
      );
      context.clip();
      drawText(context, character.text, character.x, baseline, style.colorAfter, AFTER_STROKE);
      context.restore();
    }

    if (!group.ruby) continue;
    const rubyX = group.x + (group.effectiveWidth - group.rubyWidth) / 2;
    context.font = rubyFont;
    const rubyStrokeWidth = Math.max(2, style.strokeWidth * 0.8) * scaleY;
    context.lineWidth = rubyStrokeWidth * 2.2;
    const groupProgress = group.characters.length > 0
      ? group.characters.reduce((progress, character) => progress + character.progress, 0)
        / group.characters.length
      : 0;
    const rubyCharacters = [...group.ruby.text];
    const rubyPosition = groupProgress * rubyCharacters.length;
    let characterX = rubyX;
    for (let index = 0; index < rubyCharacters.length; index += 1) {
      const text = rubyCharacters[index];
      const width = context.measureText(text).width;
      const progress = Math.min(1, Math.max(0, rubyPosition - index));
      drawText(context, text, characterX, rubyBaseline, style.colorBefore, BEFORE_STROKE);
      context.save();
      context.beginPath();
      clipCharacter(
        context,
        text,
        characterX,
        rubyBaseline,
        rubyFontSize,
        progress,
        rubyStrokeWidth,
      );
      context.clip();
      drawText(context, text, characterX, rubyBaseline, style.colorAfter, AFTER_STROKE);
      context.restore();
      characterX += width + RUBY_LETTER_SPACING * scaleX;
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
