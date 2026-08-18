import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";

export const KIRAKARA_CANVAS_WIDTH = 1280;
export const KIRAKARA_LINE_MARGIN = 128;
export const KIRAKARA_AVAILABLE_LINE_WIDTH =
  KIRAKARA_CANVAS_WIDTH - KIRAKARA_LINE_MARGIN;
export const KIRAKARA_MIN_FONT_SIZE = 48;
export const KIRAKARA_LETTER_SPACING = 9;
const KIRAKARA_RUBY_SIZE = DEFAULT_KIRAKARA_STYLE.rubySize;
const KIRAKARA_RUBY_LETTER_SPACING = 5;
const ESTIMATED_RUBY_CHARACTERS_PER_KANJI = 2;
export const KIRAKARA_FULLWIDTH_CHARACTER_LIMIT = Math.floor(
  (KIRAKARA_AVAILABLE_LINE_WIDTH + KIRAKARA_LETTER_SPACING) /
    (KIRAKARA_MIN_FONT_SIZE + KIRAKARA_LETTER_SPACING),
);

const LRC_TIMESTAMP = /\[(?:\d{1,3}):(?:\d{1,2})(?:[.:]\d{1,3})?\]/gu;
const LRC_METADATA = /^\[[^\]|]+:[^\]]*\]\s*$/u;
const CURLY_RUBY = /\{([^{}|]+)\|[^{}]*\}/gu;
const SQUARE_RUBY = /\[([^\[\]|]+)\|[^\[\]]*\]/gu;
const MAX_REPORTED_LINES = 8;
const MAX_EXCERPT_CHARACTERS = 40;

export type VisibleLyricLine = {
  lineNumber: number;
  text: string;
};

export type OverflowingLyricLine = VisibleLyricLine & {
  excerpt: string;
  characterCount: number;
  widthPx: number;
};

export type LyricsWidthOverflowReport = {
  availableWidthPx: number;
  fullwidthCharacterLimit: number;
  totalOverflowingLines: number;
  lines: OverflowingLyricLine[];
};

export type LyricsValidationSource = {
  label: string;
  text: string;
  signature: string;
};

type ReadableLyricsFile = {
  name: string;
  text: () => Promise<string>;
};

type WidthValidationOptions = {
  measureCharacter?: (character: string) => number;
  measureRubyCharacter?: (character: string) => number;
};

type CharacterMeasurers = {
  main: (character: string) => number;
  ruby: (character: string) => number;
};

function visibleLyricText(rawLine: string): string | null {
  const withoutBom = rawLine.replace(/^\uFEFF/u, "").trim();
  if (!withoutBom || /^@ruby\b/iu.test(withoutBom)) return null;

  const hadTimestamp = LRC_TIMESTAMP.test(withoutBom);
  LRC_TIMESTAMP.lastIndex = 0;
  let text = withoutBom.replace(LRC_TIMESTAMP, "").trim();
  LRC_TIMESTAMP.lastIndex = 0;

  if (!hadTimestamp && LRC_METADATA.test(text)) return null;
  text = text.replace(CURLY_RUBY, "$1").replace(SQUARE_RUBY, "$1").trim();
  return text || null;
}

export function extractVisibleLyricLines(text: string): VisibleLyricLine[] {
  return text.split(/\r?\n/u).flatMap((rawLine, index) => {
    const visible = visibleLyricText(rawLine);
    return visible ? [{ lineNumber: index + 1, text: visible }] : [];
  });
}

function fallbackCharacterWidth(character: string): number {
  if (/^[\u0000-\u00ff]$/u.test(character)) {
    return character === " " ? 12 : 24;
  }
  return KIRAKARA_MIN_FONT_SIZE;
}

function fallbackRubyCharacterWidth(): number {
  return KIRAKARA_RUBY_SIZE;
}

function isKanji(character: string): boolean {
  const codePoint = character.codePointAt(0) ?? 0;
  return (
    (codePoint >= 0x3400 && codePoint <= 0x4dbf) ||
    (codePoint >= 0x4e00 && codePoint <= 0x9fff)
  );
}

function createBrowserCharacterMeasurers(): CharacterMeasurers {
  if (typeof document === "undefined") {
    return { main: fallbackCharacterWidth, ruby: fallbackRubyCharacterWidth };
  }
  const context = document.createElement("canvas").getContext("2d");
  if (!context) {
    return { main: fallbackCharacterWidth, ruby: fallbackRubyCharacterWidth };
  }

  const measure = (
    character: string,
    fontSize: number,
    fontWeight: number,
    fallback: (character: string) => number,
  ) => {
    context.font = `${fontWeight} ${fontSize}px ${DEFAULT_KIRAKARA_STYLE.fontFamily}`;
    const width = context.measureText(character).width;
    return Number.isFinite(width) && width > 0 ? width : fallback(character);
  };

  context.fontKerning = "none";
  context.textRendering = "geometricPrecision";

  return {
    main: (character) => measure(
      character,
      KIRAKARA_MIN_FONT_SIZE,
      700,
      fallbackCharacterWidth,
    ),
    ruby: (character) => measure(
      character,
      KIRAKARA_RUBY_SIZE,
      400,
      fallbackRubyCharacterWidth,
    ),
  };
}

function measureLineWidth(
  text: string,
  measureCharacter: (character: string) => number,
  measureRubyCharacter: (character: string) => number,
): number {
  const characters = [...text];
  const glyphWidth = characters.reduce(
    (total, character) => {
      const mainWidth = measureCharacter(character);
      if (!isKanji(character)) return total + mainWidth;

      // The reading is not known yet at import time. Kirakara isolates ruby
      // groups and lets a wider reading expand the line, so reserve the common
      // two-kana reading width for every kanji instead of measuring only the base.
      const rubyCharacterWidth = measureRubyCharacter("あ");
      const estimatedRubyWidth =
        rubyCharacterWidth * ESTIMATED_RUBY_CHARACTERS_PER_KANJI +
        KIRAKARA_RUBY_LETTER_SPACING *
          (ESTIMATED_RUBY_CHARACTERS_PER_KANJI - 1);
      return total + Math.max(mainWidth, estimatedRubyWidth);
    },
    0,
  );
  return glyphWidth + Math.max(0, characters.length - 1) * KIRAKARA_LETTER_SPACING;
}

function excerpt(text: string): string {
  const characters = [...text];
  if (characters.length <= MAX_EXCERPT_CHARACTERS) return text;
  return `${characters.slice(0, MAX_EXCERPT_CHARACTERS).join("")}...`;
}

export function detectLyricsWidthOverflow(
  text: string,
  options: WidthValidationOptions = {},
): LyricsWidthOverflowReport | null {
  const browserMeasurers = createBrowserCharacterMeasurers();
  const measureCharacter = options.measureCharacter ?? browserMeasurers.main;
  const measureRubyCharacter =
    options.measureRubyCharacter ?? browserMeasurers.ruby;
  const overflowing = extractVisibleLyricLines(text).flatMap((line) => {
    const widthPx = Math.round(measureLineWidth(
      line.text,
      measureCharacter,
      measureRubyCharacter,
    ));
    if (widthPx <= KIRAKARA_AVAILABLE_LINE_WIDTH) return [];
    return [
      {
        ...line,
        excerpt: excerpt(line.text),
        characterCount: [...line.text].length,
        widthPx,
      },
    ];
  });

  if (overflowing.length === 0) return null;
  return {
    availableWidthPx: KIRAKARA_AVAILABLE_LINE_WIDTH,
    fullwidthCharacterLimit: KIRAKARA_FULLWIDTH_CHARACTER_LIMIT,
    totalOverflowingLines: overflowing.length,
    lines: overflowing.slice(0, MAX_REPORTED_LINES),
  };
}

export async function readLyricsValidationSource(
  lyricsText: string,
  lyricsFile: ReadableLyricsFile | null,
): Promise<LyricsValidationSource> {
  if (lyricsFile) {
    const text = await lyricsFile.text();
    return {
      label: lyricsFile.name,
      text,
      signature: `file:${lyricsFile.name}\u0000${text}`,
    };
  }
  return {
    label: "粘贴的歌词",
    text: lyricsText,
    signature: `text\u0000${lyricsText}`,
  };
}
