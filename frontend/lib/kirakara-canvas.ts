import type {
  KirakaraFrame,
  KirakaraFrameCharacter,
  KirakaraFrameLine,
  KirakaraFrameRuby,
  KirakaraFrameUnit,
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
  arc?(x: number, y: number, radius: number, startAngle: number, endAngle: number): void;
  fill?(): void;
  stroke?(): void;
  globalAlpha?: number;
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  lineWidth: number;
  lineJoin: CanvasLineJoin;
  miterLimit: number;
  font: string;
  textBaseline: CanvasTextBaseline;
  shadowColor?: string;
  shadowBlur?: number;
  shadowOffsetX?: number;
  shadowOffsetY?: number;
};

type LayoutGroup = {
  unitIndex: number;
  characters: Array<KirakaraFrameCharacter & { width: number; x: number }>;
  ruby: KirakaraFrameRuby | null;
  baseWidth: number;
  rubyWidth: number;
  x: number;
};

type TextPass = "main" | "shadow";

const INDICATOR_SIZE = 34;
const INDICATOR_SPACING = 12;
const INDICATOR_STROKE_WIDTH = 3;
const INDICATOR_OFFSET_Y = 8;
const MAIN_LINE_HEIGHT = 1.2;
const RUBY_LINE_HEIGHT = 1.1;
const ROMAJI_STROKE_WIDTH = 2;
const baselineCache = new Map<string, number>();

function drawText(
  context: KirakaraCanvasContext,
  text: string,
  x: number,
  y: number,
  fill: string,
  stroke: string,
  shadowColor: string,
  shadowDepth: number,
  pass: TextPass = "main",
): void {
  context.save();
  context.lineJoin = "round";
  context.miterLimit = 2;
  context.shadowColor = "transparent";
  context.shadowBlur = 0;
  context.shadowOffsetX = 0;
  context.shadowOffsetY = 0;
  const offset = pass === "shadow" ? shadowDepth : 0;
  context.strokeStyle = pass === "shadow" ? shadowColor : stroke;
  if (context.lineWidth > 0) context.strokeText(text, x + offset, y + offset);
  context.fillStyle = pass === "shadow" ? shadowColor : fill;
  context.fillText(text, x + offset, y + offset);
  context.restore();
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

function splitUnit(unit: KirakaraFrameUnit, unitIndex: number) {
  const characters = unitCharacters(unit);
  const sorted = [...unit.ruby].sort(
    (left, right) => left.startCharacter - right.startCharacter,
  );
  const groups: Array<{
    unitIndex: number;
    characters: KirakaraFrameCharacter[];
    ruby: KirakaraFrameRuby | null;
  }> = [];
  let cursor = 0;
  for (const annotation of sorted) {
    if (annotation.startCharacter > cursor) {
      groups.push({ unitIndex, characters: characters.slice(cursor, annotation.startCharacter), ruby: null });
    }
    if (annotation.endCharacter > annotation.startCharacter) {
      groups.push({
        unitIndex,
        characters: characters.slice(annotation.startCharacter, annotation.endCharacter),
        ruby: annotation,
      });
    }
    cursor = Math.max(cursor, annotation.endCharacter);
  }
  if (cursor < characters.length) {
    groups.push({ unitIndex, characters: characters.slice(cursor), ruby: null });
  }
  return groups.length > 0 ? groups : [{ unitIndex, characters, ruby: null }];
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
  const mainFont = `${style.fontBold ? "700" : "normal"} ${mainFontSize}px ${style.fontFamily}`;
  const rubyFont = `400 ${rubyFontSize}px ${style.fontFamily}`;
  const sourceGroups = line.units.flatMap((unit, unitIndex) =>
    splitUnit(unit, unitIndex),
  );

  const groups = sourceGroups.map((group): LayoutGroup => {
    context.font = mainFont;
    const characters = group.characters.map((character) => ({
      ...character,
      width: context.measureText(character.text).width,
      x: 0,
    }));
    const baseWidth = characters.reduce((width, character) => width + character.width, 0)
      + Math.max(0, characters.length - 1) * style.letterSpacing * scaleX;
    context.font = rubyFont;
    const rubyCharacters = group.ruby ? [...group.ruby.text] : [];
    const rubyWidth = rubyCharacters.reduce(
      (width, character) => width + context.measureText(character).width,
      0,
    ) + Math.max(0, rubyCharacters.length - 1) * style.rubyLetterSpacing * scaleX;
    return {
      ...group,
      characters,
      baseWidth,
      rubyWidth,
      x: 0,
    };
  });

  const groupSpacing = style.letterSpacing * scaleX;
  const totalWidth = groups.reduce((total, group) => total + group.baseWidth, 0)
    + Math.max(0, groups.length - 1) * groupSpacing;
  const left = style.horizontalMargin * scaleX;
  let cursorX = line.slot === "upper" ? left : context.canvas.width - left - totalWidth;
  for (const group of groups) {
    group.x = cursorX;
    let characterX = cursorX;
    for (const character of group.characters) {
      character.x = characterX;
      characterX += character.width + style.letterSpacing * scaleX;
    }
    cursorX += group.baseWidth + groupSpacing;
  }
  return groups;
}

function packLabelLefts(
  labels: Array<{ left: number; width: number }>,
  gap: number,
): number[] {
  if (labels.length <= 1) return labels.map(({ left }) => left);

  const offsets: number[] = [];
  let offset = 0;
  for (const label of labels) {
    offsets.push(offset);
    offset += label.width + gap;
  }
  const blocks: Array<{
    start: number;
    end: number;
    weight: number;
    value: number;
  }> = [];
  labels.forEach(({ left }, index) => {
    blocks.push({
      start: index,
      end: index,
      weight: 1,
      value: left - offsets[index],
    });
    while (
      blocks.length >= 2
      && blocks[blocks.length - 2].value > blocks[blocks.length - 1].value
    ) {
      const right = blocks.pop()!;
      const leftBlock = blocks.pop()!;
      const weight = leftBlock.weight + right.weight;
      blocks.push({
        start: leftBlock.start,
        end: right.end,
        weight,
        value: (
          leftBlock.value * leftBlock.weight
          + right.value * right.weight
        ) / weight,
      });
    }
  });

  const packed = new Array<number>(labels.length);
  for (const block of blocks) {
    for (let index = block.start; index <= block.end; index += 1) {
      packed[index] = block.value + offsets[index];
    }
  }
  return packed;
}

function drawLine(
  context: KirakaraCanvasContext,
  line: KirakaraFrameLine,
  style: KirakaraStyle,
  scaleX: number,
  scaleY: number,
  pass: TextPass = "main",
): void {
  const fontSize = style.fontSize * scaleY;
  const rubyFontSize = style.rubySize * scaleY;
  const romajiSize = style.romajiFollowRuby ? style.rubySize : style.romajiSize;
  const romajiLetterSpacing = style.romajiFollowRuby
    ? style.rubyLetterSpacing
    : style.romajiLetterSpacing;
  const romajiOffset = style.romajiFollowRuby ? style.rubyOffset : style.romajiOffset;
  const romajiFontSize = romajiSize * scaleY;
  const mainFont = `${style.fontBold ? "700" : "normal"} ${fontSize}px ${style.fontFamily}`;
  const rubyFont = `400 ${rubyFontSize}px ${style.fontFamily}`;
  const romajiFont = `700 ${romajiFontSize}px ${style.fontFamily}`;
  const groups = layoutLine(context, line, style, scaleX, scaleY);
  const lineTop = (line.slot === "upper" ? style.upperY : style.lowerY) * scaleY;
  const baseline = lineTop + measureBaselineOffset(
    fontSize,
    style.fontFamily,
    style.fontBold ? "700" : "normal",
    MAIN_LINE_HEIGHT,
  );
  const rubyBaselineOffset = measureBaselineOffset(
    rubyFontSize,
    style.fontFamily,
    "normal",
    RUBY_LINE_HEIGHT,
  );
  const rubyAboveBaseline = lineTop
    - style.rubyOffset * scaleY
    - (rubyFontSize * RUBY_LINE_HEIGHT - rubyBaselineOffset);
  const rubyTop = lineTop
    - style.rubyOffset * scaleY
    - rubyFontSize * RUBY_LINE_HEIGHT;
  const romajiBaselineOffset = measureBaselineOffset(
    romajiFontSize,
    style.fontFamily,
    "700",
    RUBY_LINE_HEIGHT,
  );
  const romajiAboveBaseline = rubyTop
    - romajiOffset * scaleY
    - (romajiFontSize * RUBY_LINE_HEIGHT - romajiBaselineOffset);
  const romajiBelowBaseline = lineTop
    + fontSize * MAIN_LINE_HEIGHT
    + romajiOffset * scaleY
    + romajiBaselineOffset;

  const previousAlpha = context.globalAlpha ?? 1;
  context.globalAlpha = previousAlpha * (line.opacity ?? 1);

  if (pass === "main" && line.indicatorOpacities && context.arc && context.fill && context.stroke) {
    const radius = INDICATOR_SIZE * scaleY / 2;
    const dotSize = INDICATOR_SIZE * scaleY;
    const spacing = INDICATOR_SPACING * scaleX;
    const baseX = style.horizontalMargin * scaleX;
    const hasRomajiAbove = line.units.some(
      (unit) => unit.romaji?.position === "above",
    );
    const baseY = lineTop
      - (
        style.rubySize
        + style.rubyOffset
        + (hasRomajiAbove ? romajiSize + romajiOffset : 0)
        + INDICATOR_OFFSET_Y
      ) * scaleY;
    line.indicatorOpacities.forEach((opacity, index) => {
      if (opacity <= 0) return;
      context.globalAlpha = previousAlpha * (line.opacity ?? 1) * opacity;
      context.beginPath();
      context.arc?.(
        baseX + index * (dotSize + spacing) + radius,
        baseY - dotSize + radius,
        radius - INDICATOR_STROKE_WIDTH * scaleY / 2,
        0,
        Math.PI * 2,
      );
      context.fillStyle = "#ffffff";
      context.fill?.();
      context.strokeStyle = "#000000";
      context.lineWidth = INDICATOR_STROKE_WIDTH * scaleY;
      context.stroke?.();
    });
    context.globalAlpha = previousAlpha * (line.opacity ?? 1);
  }

  const rubyGroups = groups.filter((group) => group.ruby !== null);
  const rubyLefts = packLabelLefts(
    rubyGroups.map((group) => ({
      left: group.x + (group.baseWidth - group.rubyWidth) / 2,
      width: group.rubyWidth,
    })),
    style.rubyLetterSpacing * scaleX,
  );
  const rubyLeftByGroup = new Map(
    rubyGroups.map((group, index) => [group, rubyLefts[index]]),
  );

  context.textBaseline = "alphabetic";
  for (const group of groups) {
    context.font = mainFont;
    const mainStrokeWidth = style.strokeWidth * scaleY;
    context.lineWidth = mainStrokeWidth * 2.2;
    for (const character of group.characters) {
      drawText(
        context,
        character.text,
        character.x,
        baseline,
        pass === "shadow" ? style.shadowColor : style.colorBefore,
        pass === "shadow" ? style.shadowColor : style.strokeColorBefore,
        style.shadowColor,
        style.shadowDepth * scaleY,
        pass,
      );
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
      drawText(
        context,
        character.text,
        character.x,
        baseline,
        pass === "shadow" ? style.shadowColor : style.colorAfter,
        pass === "shadow" ? style.shadowColor : style.strokeColorAfter,
        style.shadowColor,
        style.shadowDepth * scaleY,
        pass,
      );
      context.restore();
    }

    if (!group.ruby) continue;
    const rubyX = rubyLeftByGroup.get(group)
      ?? group.x + (group.baseWidth - group.rubyWidth) / 2;
    const rubyBaseline = rubyAboveBaseline;
    context.font = rubyFont;
    const rubyStrokeWidth = Math.round(style.strokeWidth * 0.8) * scaleY;
    context.lineWidth = rubyStrokeWidth * 2.2;
    const groupProgress = group.characters.length > 0
      ? group.characters.reduce((progress, character) => progress + character.progress, 0)
        / group.characters.length
      : 0;
    const fallbackRubyCharacters = [...group.ruby.text].map((text, index, characters) => ({
      text,
      progress: Math.min(1, Math.max(0, groupProgress * characters.length - index)),
    }));
    const rubyCharacters = group.ruby.characters
      ?.map(({ text }) => text).join("") === group.ruby.text
        ? group.ruby.characters
        : fallbackRubyCharacters;
    let characterX = rubyX;
    for (let index = 0; index < rubyCharacters.length; index += 1) {
      const { text, progress } = rubyCharacters[index];
      const width = context.measureText(text).width;
      drawText(
        context,
        text,
        characterX,
        rubyBaseline,
        pass === "shadow" ? style.shadowColor : style.colorBefore,
        pass === "shadow" ? style.shadowColor : style.strokeColorBefore,
        style.shadowColor,
        style.shadowDepth * scaleY,
        pass,
      );
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
      drawText(
        context,
        text,
        characterX,
        rubyBaseline,
        pass === "shadow" ? style.shadowColor : style.colorAfter,
        pass === "shadow" ? style.shadowColor : style.strokeColorAfter,
        style.shadowColor,
        style.shadowDepth * scaleY,
        pass,
      );
      context.restore();
      characterX += width + style.rubyLetterSpacing * scaleX;
    }
  }

  const romajiLayouts: Array<{
    segments: Array<{
      text: string;
      characters: Array<{ text: string; progress: number }>;
    }>;
    segmentWidths: number[];
    textWidth: number;
    naturalLeft: number;
    baseline: number;
  }> = [];
  for (let unitIndex = 0; unitIndex < line.units.length; unitIndex += 1) {
    const unit = line.units[unitIndex];
    if (!unit.romaji) continue;
    const unitGroups = groups.filter((group) => group.unitIndex === unitIndex);
    const firstGroup = unitGroups[0];
    const lastGroup = unitGroups.at(-1);
    if (!firstGroup || !lastGroup) continue;

    const fallbackCharacters = [...unit.romaji.text].map((text, index, characters) => ({
      text,
      progress: Math.min(1, Math.max(0, unit.progress * characters.length - index)),
    }));
    const characters = unit.romaji.characters
      ?.map(({ text }) => text).join("") === unit.romaji.text
        ? unit.romaji.characters
        : fallbackCharacters;
    const sourceSegments = unit.romaji.segments
      ?.filter((segment) => segment.text.length > 0)
      .map((segment) => ({
        ...segment,
        characters: segment.characters
          .map(({ text }) => text).join("") === segment.text
            ? segment.characters
            : [...segment.text].map((text) => ({ text, progress: unit.progress })),
      }));
    const segments = sourceSegments
      && sourceSegments.map(({ text }) => text).join("") === unit.romaji.text
      ? sourceSegments
      : [{ text: unit.romaji.text, characters }];
    context.font = romajiFont;
    const segmentWidths = segments.map(({ text }) => context.measureText(text).width);
    const textWidth = segmentWidths.reduce((total, width) => total + width, 0)
      + Math.max(0, segments.length - 1) * romajiLetterSpacing * scaleX;
    const unitLeft = firstGroup.x;
    const unitRight = lastGroup.x + lastGroup.baseWidth;
    romajiLayouts.push({
      segments,
      segmentWidths,
      textWidth,
      naturalLeft: unitLeft + (unitRight - unitLeft - textWidth) / 2,
      baseline: unit.romaji.position === "above"
        ? romajiAboveBaseline
        : romajiBelowBaseline,
    });
  }

  const romajiLefts = new Array<number>(romajiLayouts.length);
  const layoutsByBaseline = new Map<number, number[]>();
  romajiLayouts.forEach(({ baseline }, index) => {
    const indexes = layoutsByBaseline.get(baseline) ?? [];
    indexes.push(index);
    layoutsByBaseline.set(baseline, indexes);
  });
  for (const indexes of layoutsByBaseline.values()) {
    const packed = packLabelLefts(
      indexes.map((index) => ({
        left: romajiLayouts[index].naturalLeft,
        width: romajiLayouts[index].textWidth,
      })),
      romajiLetterSpacing * scaleX,
    );
    indexes.forEach((layoutIndex, packedIndex) => {
      romajiLefts[layoutIndex] = packed[packedIndex];
    });
  }

  const strokeWidth = ROMAJI_STROKE_WIDTH * scaleY;
  romajiLayouts.forEach((layout, layoutIndex) => {
    const {
      segments,
      segmentWidths,
      baseline: romajiBaseline,
    } = layout;
    let segmentX = romajiLefts[layoutIndex];
    context.lineWidth = strokeWidth * 2.2;

    segments.forEach((segment, segmentIndex) => {
      let prefix = "";
      segment.characters.forEach(({ text, progress }) => {
        const characterX = segmentX + context.measureText(prefix).width;
        drawText(
          context,
          text,
          characterX,
          romajiBaseline,
          pass === "shadow" ? style.shadowColor : style.colorBefore,
          pass === "shadow" ? style.shadowColor : style.strokeColorBefore,
          style.shadowColor,
          style.shadowDepth * scaleY,
          pass,
        );
        context.save();
        context.beginPath();
        clipCharacter(
          context,
          text,
          characterX,
          romajiBaseline,
          romajiFontSize,
          progress,
          strokeWidth,
        );
        context.clip();
        drawText(
          context,
          text,
          characterX,
          romajiBaseline,
          pass === "shadow" ? style.shadowColor : style.colorAfter,
          pass === "shadow" ? style.shadowColor : style.strokeColorAfter,
          style.shadowColor,
          style.shadowDepth * scaleY,
          pass,
        );
        context.restore();
        prefix += text;
      });
      segmentX += segmentWidths[segmentIndex] + romajiLetterSpacing * scaleX;
    });
  });
  context.globalAlpha = previousAlpha;
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
  if (style.shadowDepth > 0) {
    for (const line of frame.lines) drawLine(context, line, style, scaleX, scaleY, "shadow");
  }
  for (const line of frame.lines) drawLine(context, line, style, scaleX, scaleY);
}
