export type KirakaraStyle = {
  fontFamily: string;
  fontSize: number;
  fontBold: boolean;
  letterSpacing: number;
  rubySize: number;
  rubyLetterSpacing: number;
  rubyOffset: number;
  /** Video-preview/export-only controls; the KRL config stays SUG-compatible. */
  romajiFollowRuby: boolean;
  romajiSize: number;
  romajiLetterSpacing: number;
  romajiOffset: number;
  colorBefore: string;
  colorAfter: string;
  strokeColorBefore: string;
  strokeColorAfter: string;
  strokeWidth: number;
  shadowColor: string;
  shadowDepth: number;
  horizontalMargin: number;
  upperY: number;
  lowerY: number;
};

export type KirakaraStylePreset = {
  id: string;
  label: string;
  style: KirakaraStyle;
};

export const KIRAKARA_STYLE_STORAGE_KEY = "nicokara-kirakara-style-v1";

export const DEFAULT_KIRAKARA_STYLE: KirakaraStyle = Object.freeze({
  fontFamily: '"Noto Sans JP", "Yu Gothic", sans-serif',
  fontSize: 64,
  fontBold: true,
  letterSpacing: 9,
  rubySize: 26,
  rubyLetterSpacing: 5,
  rubyOffset: 4,
  romajiFollowRuby: true,
  romajiSize: 26,
  romajiLetterSpacing: 5,
  romajiOffset: 4,
  colorBefore: "#ffffff",
  colorAfter: "#a50000",
  strokeColorBefore: "#000000",
  strokeColorAfter: "#ffffff",
  strokeWidth: 5,
  shadowColor: "#000000",
  shadowDepth: 0,
  horizontalMargin: 128,
  upperY: 430,
  lowerY: 563,
});

export const KIRAKARA_STYLE_PRESETS: readonly KirakaraStylePreset[] = Object.freeze([
  { id: "classic", label: "经典卡拉 OK", style: DEFAULT_KIRAKARA_STYLE },
  {
    id: "compact",
    label: "紧凑小字",
    style: Object.freeze({
      ...DEFAULT_KIRAKARA_STYLE,
      fontSize: 44,
      rubySize: 18,
      letterSpacing: 5,
      rubyLetterSpacing: 3,
      strokeWidth: 3,
      horizontalMargin: 88,
    }),
  },
  {
    id: "soft-shadow",
    label: "柔和阴影",
    style: Object.freeze({
      ...DEFAULT_KIRAKARA_STYLE,
      fontSize: 56,
      rubySize: 22,
      letterSpacing: 6,
      rubyLetterSpacing: 4,
      strokeWidth: 3,
      shadowDepth: 4,
      horizontalMargin: 104,
    }),
  },
]);

const COLOR = /^#[0-9a-f]{6}$/i;
const UNSAFE_FONT_FAMILY = /[\u0000-\u001f\u007f<>;{}]/u;

function fontFamily(value: unknown): string {
  if (typeof value !== "string") return DEFAULT_KIRAKARA_STYLE.fontFamily;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 200 || UNSAFE_FONT_FAMILY.test(trimmed)) {
    return DEFAULT_KIRAKARA_STYLE.fontFamily;
  }
  return trimmed;
}

function numberInRange(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.round(parsed)));
}

function color(value: unknown, fallback: string): string {
  return typeof value === "string" && COLOR.test(value) ? value.toLowerCase() : fallback;
}

function boolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizeKirakaraStyle(
  value: Partial<KirakaraStyle> | null | undefined,
): KirakaraStyle {
  const source = value ?? {};
  const rubySize = numberInRange(
    source.rubySize,
    DEFAULT_KIRAKARA_STYLE.rubySize,
    10,
    60,
  );
  const rubyLetterSpacing = numberInRange(
    source.rubyLetterSpacing,
    DEFAULT_KIRAKARA_STYLE.rubyLetterSpacing,
    -2,
    20,
  );
  const rubyOffset = numberInRange(
    source.rubyOffset,
    DEFAULT_KIRAKARA_STYLE.rubyOffset,
    0,
    32,
  );
  return {
    fontFamily: fontFamily(source.fontFamily),
    fontSize: numberInRange(source.fontSize, DEFAULT_KIRAKARA_STYLE.fontSize, 24, 120),
    fontBold: boolean(source.fontBold, DEFAULT_KIRAKARA_STYLE.fontBold),
    letterSpacing: numberInRange(source.letterSpacing, DEFAULT_KIRAKARA_STYLE.letterSpacing, -4, 32),
    rubySize,
    rubyLetterSpacing,
    rubyOffset,
    romajiFollowRuby: boolean(
      source.romajiFollowRuby,
      DEFAULT_KIRAKARA_STYLE.romajiFollowRuby,
    ),
    romajiSize: numberInRange(source.romajiSize, rubySize, 10, 60),
    romajiLetterSpacing: numberInRange(
      source.romajiLetterSpacing,
      rubyLetterSpacing,
      -2,
      20,
    ),
    romajiOffset: numberInRange(source.romajiOffset, rubyOffset, 0, 32),
    colorBefore: color(source.colorBefore, DEFAULT_KIRAKARA_STYLE.colorBefore),
    colorAfter: color(source.colorAfter, DEFAULT_KIRAKARA_STYLE.colorAfter),
    strokeColorBefore: color(source.strokeColorBefore, DEFAULT_KIRAKARA_STYLE.strokeColorBefore),
    strokeColorAfter: color(source.strokeColorAfter, DEFAULT_KIRAKARA_STYLE.strokeColorAfter),
    strokeWidth: numberInRange(source.strokeWidth, DEFAULT_KIRAKARA_STYLE.strokeWidth, 0, 12),
    shadowColor: color(source.shadowColor, DEFAULT_KIRAKARA_STYLE.shadowColor),
    shadowDepth: numberInRange(source.shadowDepth, DEFAULT_KIRAKARA_STYLE.shadowDepth, 0, 12),
    horizontalMargin: numberInRange(source.horizontalMargin, DEFAULT_KIRAKARA_STYLE.horizontalMargin, 0, 320),
    upperY: numberInRange(source.upperY, DEFAULT_KIRAKARA_STYLE.upperY, 120, 600),
    lowerY: numberInRange(source.lowerY, DEFAULT_KIRAKARA_STYLE.lowerY, 240, 700),
  };
}

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem">;

export function loadKirakaraStyle(storage: StorageReader): KirakaraStyle {
  try {
    const saved = storage.getItem(KIRAKARA_STYLE_STORAGE_KEY);
    if (!saved) return DEFAULT_KIRAKARA_STYLE;
    return normalizeKirakaraStyle(JSON.parse(saved) as Partial<KirakaraStyle>);
  } catch {
    return DEFAULT_KIRAKARA_STYLE;
  }
}

export function saveKirakaraStyle(
  storage: StorageWriter,
  style: KirakaraStyle,
): void {
  storage.setItem(KIRAKARA_STYLE_STORAGE_KEY, JSON.stringify(normalizeKirakaraStyle(style)));
}

export function kirakaraStylePayload(style: KirakaraStyle) {
  const normalized = normalizeKirakaraStyle(style);
  const firstFontFamily = normalized.fontFamily.split(",")[0].trim();
  return {
    font_family: firstFontFamily.replace(/^(['"])(.*)\1$/u, "$2"),
    font_size: normalized.fontSize,
    font_bold: normalized.fontBold,
    letter_spacing: normalized.letterSpacing,
    ruby_size: normalized.rubySize,
    ruby_letter_spacing: normalized.rubyLetterSpacing,
    ruby_offset: normalized.rubyOffset,
    romaji_follow_ruby: normalized.romajiFollowRuby,
    romaji_size: normalized.romajiSize,
    romaji_letter_spacing: normalized.romajiLetterSpacing,
    romaji_offset: normalized.romajiOffset,
    color_before: normalized.colorBefore,
    color_after: normalized.colorAfter,
    stroke_color_before: normalized.strokeColorBefore,
    stroke_color_after: normalized.strokeColorAfter,
    stroke_width: normalized.strokeWidth,
    shadow_color: normalized.shadowColor,
    shadow_depth: normalized.shadowDepth,
    horizontal_margin: normalized.horizontalMargin,
    upper_y: normalized.upperY,
    lower_y: normalized.lowerY,
  };
}
