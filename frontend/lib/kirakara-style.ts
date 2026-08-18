export type KirakaraStyle = {
  fontFamily: string;
  fontSize: number;
  rubySize: number;
  colorBefore: string;
  colorAfter: string;
  strokeWidth: number;
  upperY: number;
  lowerY: number;
};

export const KIRAKARA_STYLE_STORAGE_KEY = "nicokara-kirakara-style-v1";

export const DEFAULT_KIRAKARA_STYLE: KirakaraStyle = Object.freeze({
  fontFamily: '"Noto Sans JP", "Yu Gothic", sans-serif',
  fontSize: 64,
  rubySize: 26,
  colorBefore: "#ffffff",
  colorAfter: "#a50000",
  strokeWidth: 5,
  upperY: 430,
  lowerY: 563,
});

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

export function normalizeKirakaraStyle(
  value: Partial<KirakaraStyle> | null | undefined,
): KirakaraStyle {
  const source = value ?? {};
  return {
    fontFamily: fontFamily(source.fontFamily),
    fontSize: numberInRange(source.fontSize, DEFAULT_KIRAKARA_STYLE.fontSize, 48, 80),
    rubySize: numberInRange(source.rubySize, DEFAULT_KIRAKARA_STYLE.rubySize, 18, 38),
    colorBefore: color(source.colorBefore, DEFAULT_KIRAKARA_STYLE.colorBefore),
    colorAfter: color(source.colorAfter, DEFAULT_KIRAKARA_STYLE.colorAfter),
    strokeWidth: numberInRange(source.strokeWidth, DEFAULT_KIRAKARA_STYLE.strokeWidth, 2, 8),
    upperY: numberInRange(source.upperY, DEFAULT_KIRAKARA_STYLE.upperY, 320, 560),
    lowerY: numberInRange(source.lowerY, DEFAULT_KIRAKARA_STYLE.lowerY, 440, 680),
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
    ruby_size: normalized.rubySize,
    color_before: normalized.colorBefore,
    color_after: normalized.colorAfter,
    stroke_width: normalized.strokeWidth,
    upper_y: normalized.upperY,
    lower_y: normalized.lowerY,
  };
}
