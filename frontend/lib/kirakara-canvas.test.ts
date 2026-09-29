import { describe, expect, it, vi } from "vitest";

import { drawKirakaraFrame } from "./kirakara-canvas";
import { DEFAULT_KIRAKARA_STYLE } from "./kirakara-style";
import type { KirakaraFrame } from "./kirakara-timeline";

function context(
  measureText: (text: string, font: string) => number = (text) =>
    [...text].length * 40,
) {
  const strokeStates: Array<{
    lineJoin: CanvasLineJoin;
    miterLimit: number;
    lineWidth: number;
    strokeStyle: string | CanvasGradient | CanvasPattern;
    shadowColor?: string;
  }> = [];
  const fillStates: Array<{ text: string; x: number; y: number; font: string }> = [];
  const canvasContext = {
    canvas: { width: 1280, height: 720 },
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn((text: string, x: number, y: number) => {
      fillStates.push({ text, x, y, font: canvasContext.font });
    }),
    strokeText: vi.fn(() => {
      strokeStates.push({
        lineJoin: canvasContext.lineJoin,
        miterLimit: canvasContext.miterLimit,
        lineWidth: canvasContext.lineWidth,
        strokeStyle: canvasContext.strokeStyle,
        shadowColor: canvasContext.shadowColor,
      });
    }),
    measureText: vi.fn((text: string) => ({
      width: measureText(text, canvasContext.font),
    })),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    globalAlpha: 1,
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    font: "",
    textBaseline: "alphabetic" as CanvasTextBaseline,
    lineJoin: "miter" as CanvasLineJoin,
    miterLimit: 10,
    shadowColor: "transparent",
    shadowBlur: 0,
    shadowOffsetX: 0,
    shadowOffsetY: 0,
    strokeStates,
    fillStates,
  };
  return canvasContext;
}

const frame: KirakaraFrame = {
  lines: [
    {
      slot: "upper",
      text: "今日も",
      units: [
        {
          text: "今日",
          progress: 0.5,
          ruby: [{ text: "きょう", startCharacter: 0, endCharacter: 2 }],
        },
        { text: "も", progress: 0, ruby: [] },
      ],
    },
    {
      slot: "lower",
      text: "歌う",
      units: [
        {
          text: "歌",
          progress: 0,
          ruby: [{ text: "うた", startCharacter: 0, endCharacter: 1 }],
        },
        { text: "う", progress: 0, ruby: [] },
      ],
    },
  ],
};

describe("drawKirakaraFrame", () => {
  it("draws alternating upper-left and lower-right lyric lines", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, frame);

    expect(canvas.fillText).toHaveBeenCalledWith("今", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("日", 177, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("歌", 1063, expect.any(Number));
    const upperCall = canvas.fillText.mock.calls.find(([text]) => text === "今");
    const lowerCall = canvas.fillText.mock.calls.find(([text]) => text === "歌");
    expect(upperCall?.[2]).toBeCloseTo(492.72, 2);
    expect(lowerCall?.[2]).toBeCloseTo(625.72, 2);
    expect(canvas.fillRect).not.toHaveBeenCalled();
  });

  it("draws ruby over kanji groups and clips sung progress", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, frame);

    expect(canvas.fillText).toHaveBeenCalledWith("き", 107.5, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("ょ", 152.5, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("う", 197.5, expect.any(Number));
    const rubyCall = canvas.fillText.mock.calls.find(([text]) => text === "き");
    expect(rubyCall?.[2]).toBeCloseTo(421.58, 2);
    expect(
      canvas.fillText.mock.calls.filter(([text]) => text === "も"),
    ).toHaveLength(2);
    expect(canvas.rect).toHaveBeenCalled();
  });

  it("can overlay lyrics without clearing an already-drawn video frame", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, frame, { clear: false });

    expect(canvas.clearRect).not.toHaveBeenCalled();
    expect(canvas.fillText).toHaveBeenCalled();
  });

  it("clips every base character independently instead of wiping a whole token", () => {
    const canvas = context();
    const characterFrame = {
      lines: [
        {
          slot: "upper" as const,
          text: "東京",
          units: [
            {
              text: "東京",
              progress: 0.625,
              characters: [
                { text: "東", progress: 1 },
                { text: "京", progress: 0.25 },
              ],
              ruby: [],
            },
          ],
        },
      ],
    } as unknown as KirakaraFrame;

    drawKirakaraFrame(canvas, characterFrame);

    expect(canvas.rect).toHaveBeenCalledTimes(2);
    expect(canvas.rect.mock.calls[0][0]).toBe(64);
    expect(canvas.rect.mock.calls[1][0]).toBe(113);
    expect(canvas.rect.mock.calls[0][0]).not.toBe(canvas.rect.mock.calls[1][0]);
  });

  it("uses Kirakara's expanded Canvas stroke width", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [
        {
          slot: "upper",
          text: "歌",
          units: [{ text: "歌", progress: 0, ruby: [] }],
        },
      ],
    });

    expect(canvas.lineWidth).toBeCloseTo(11, 5);
  });

  it("uses Kirakara's rounded join for every Canvas text outline", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, frame);

    expect(canvas.strokeStates.length).toBeGreaterThan(0);
    expect(canvas.strokeStates.every(({ lineJoin }) => lineJoin === "round")).toBe(true);
    expect(canvas.strokeStates.every(({ miterLimit }) => miterLimit === 2)).toBe(true);
  });

  it("draws the paragraph indicator supplied by the shared Kirakara frame", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [
        {
          slot: "upper",
          text: "line",
          opacity: 1,
          indicatorOpacities: [1, 0, 0, 0],
          units: [{ text: "line", progress: 0, ruby: [] }],
        },
      ],
    });

    expect(canvas.arc).toHaveBeenCalledTimes(1);
  });

  it("measures the kanji base with the main font before centering ruby", () => {
    const canvas = context((text, font) =>
      [...text].length * (font.startsWith("700") ? 40 : 10),
    );

    drawKirakaraFrame(canvas, {
      lines: [
        {
          slot: "upper",
          text: "今日",
          units: [
            {
              text: "今日",
              progress: 0,
              ruby: [
                { text: "きょう", startCharacter: 0, endCharacter: 2 },
              ],
            },
          ],
        },
      ],
    });

    expect(canvas.fillText).toHaveBeenCalledWith("き", 152.5, expect.any(Number));
  });

  it("keeps base character spacing uniform when ruby is wider than its kanji", () => {
    const canvas = context((text, font) =>
      [...text].length * (font.startsWith("700") ? 40 : 20),
    );

    drawKirakaraFrame(canvas, {
      lines: [
        {
          slot: "upper",
          text: "火山",
          units: [
            {
              text: "火",
              progress: 0,
              ruby: [
                { text: "ほのお", startCharacter: 0, endCharacter: 1 },
              ],
            },
            { text: "山", progress: 0, ruby: [] },
          ],
        },
      ],
    });

    expect(canvas.fillText).toHaveBeenCalledWith("火", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("ほ", 113, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("山", 177, expect.any(Number));
  });

  it("separates adjacent wide ruby labels without moving the base text", () => {
    const canvas = context((text, font) =>
      [...text].length * (font.includes("64px") ? 40 : 20),
    );

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "火山",
        units: [
          {
            text: "火",
            progress: 0,
            ruby: [{ text: "あいう", startCharacter: 0, endCharacter: 1 }],
          },
          {
            text: "山",
            progress: 0,
            ruby: [{ text: "えおか", startCharacter: 0, endCharacter: 1 }],
          },
        ],
      }],
    });

    expect(canvas.fillText).toHaveBeenCalledWith("火", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("山", 177, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("あ", 100, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("え", 175, expect.any(Number));
  });

  it("separates adjacent wide romaji labels without moving the base text", () => {
    const canvas = context((text, font) =>
      [...text].length * (font.includes("64px") ? 40 : 10),
    );

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "火山",
        units: [
          {
            text: "火",
            progress: 0,
            ruby: [],
            romaji: {
              text: "abcdef",
              position: "above",
              characters: [..."abcdef"].map((text) => ({ text, progress: 0 })),
            },
          },
          {
            text: "山",
            progress: 0,
            ruby: [],
            romaji: {
              text: "ghijkl",
              position: "above",
              characters: [..."ghijkl"].map((text) => ({ text, progress: 0 })),
            },
          },
        ],
      }],
    } as KirakaraFrame);

    expect(canvas.fillText).toHaveBeenCalledWith("火", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("山", 177, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("a", 110, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("g", 175, expect.any(Number));
  });

  it("REQ-STYLE-CANVAS-01 applies custom weight, margin, outline, and shadow", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "歌",
        units: [{ text: "歌", progress: 0, ruby: [] }],
      }],
    }, {
      style: {
        ...DEFAULT_KIRAKARA_STYLE,
        fontBold: false,
        horizontalMargin: 80,
        strokeColorBefore: "#123456",
        strokeColorAfter: "#abcdef",
        shadowColor: "#654321",
        shadowDepth: 4,
      },
    });

    expect(canvas.fillText).toHaveBeenCalledWith("歌", 80, expect.any(Number));
    expect(canvas.font).toContain("normal 64px");
    expect(canvas.strokeStates.some(({ strokeStyle }) => strokeStyle === "#654321")).toBe(true);
    expect(canvas.shadowColor).toBe("transparent");
    expect(canvas.shadowOffsetX).toBe(0);
    expect(canvas.strokeStyle).toBe("#abcdef");
  });

  it("draws the optional romaji layer above the kana ruby", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "今日",
        units: [{
          text: "今日",
          progress: 0.5,
          ruby: [{ text: "きょう", startCharacter: 0, endCharacter: 2 }],
          romaji: {
            text: "kyou",
            position: "above",
            characters: [..."kyou"].map((text) => ({ text, progress: 0.5 })),
          },
        }],
      }],
    } as KirakaraFrame);

    const mainY = canvas.fillText.mock.calls.find(([text]) => text === "今")![2];
    const kanaY = canvas.fillText.mock.calls.find(([text]) => text === "き")![2];
    const romajiY = canvas.fillText.mock.calls.find(([text]) => text === "k")![2];
    expect(romajiY).toBeTypeOf("number");
    expect(romajiY).toBeLessThan(kanaY);
    expect(kanaY).toBeLessThan(mainY);
  });

  it("can draw romaji below the base text", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "今日",
        units: [{
          text: "今日",
          progress: 0.5,
          ruby: [{ text: "きょう", startCharacter: 0, endCharacter: 2 }],
          romaji: {
            text: "kyou",
            position: "below",
            characters: [..."kyou"].map((text) => ({ text, progress: 0.5 })),
          },
        }],
      }],
    } as KirakaraFrame);

    const mainY = canvas.fillText.mock.calls.find(([text]) => text === "今")![2];
    const romajiY = canvas.fillText.mock.calls.find(([text]) => text === "k")![2];
    expect(romajiY).toBeGreaterThan(mainY);
  });

  it("uses kana settings for romaji by default and allows independent preview overrides", () => {
    const drawWithStyle = (style: typeof DEFAULT_KIRAKARA_STYLE) => {
      const canvas = context();
      drawKirakaraFrame(canvas, {
        lines: [{
          slot: "upper",
          text: "今日",
          units: [{
            text: "今日",
            progress: 0.5,
            ruby: [{ text: "きょう", startCharacter: 0, endCharacter: 2 }],
            romaji: {
              text: "ky",
              position: "below",
              characters: [..."ky"].map((text) => ({ text, progress: 0.5 })),
            },
          }],
        }],
      } as KirakaraFrame, { style });
      return canvas;
    };

    const following = drawWithStyle({
      ...DEFAULT_KIRAKARA_STYLE,
      rubySize: 34,
      rubyLetterSpacing: 7,
      rubyOffset: 9,
    });
    const followingK = following.fillStates.find(({ text }) => text === "k")!;
    const followingY = following.fillStates.find(({ text }) => text === "y")!;
    expect(followingK.font).toContain("34px");
    expect(followingY.x - followingK.x).toBe(40);

    const independent = drawWithStyle({
      ...DEFAULT_KIRAKARA_STYLE,
      romajiFollowRuby: false,
      romajiSize: 30,
      romajiLetterSpacing: 3,
      romajiOffset: 15,
    });
    const independentK = independent.fillStates.find(({ text }) => text === "k")!;
    const independentY = independent.fillStates.find(({ text }) => text === "y")!;
    expect(independentK.font).toContain("30px");
    expect(independentY.x - independentK.x).toBe(40);
    expect(independentK.y).toBeGreaterThan(followingK.y);
  });

  it("applies romaji spacing between mora groups instead of between letters", () => {
    const canvas = context((text) => [...text].length * 10);

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "今日",
        units: [{
          text: "今日",
          progress: 0.5,
          ruby: [],
          romaji: {
            text: "kyou",
            position: "above",
            characters: [..."kyou"].map((text) => ({ text, progress: 0.5 })),
            segments: [
              {
                text: "kyo",
                characters: [..."kyo"].map((text) => ({ text, progress: 0.5 })),
              },
              {
                text: "u",
                characters: [{ text: "u", progress: 0.5 }],
              },
            ],
          },
        }],
      }],
    } as unknown as KirakaraFrame, {
      style: {
        ...DEFAULT_KIRAKARA_STYLE,
        romajiFollowRuby: false,
        romajiLetterSpacing: 8,
      },
    });

    const k = canvas.fillStates.find(({ text }) => text === "k")!;
    const y = canvas.fillStates.find(({ text }) => text === "y")!;
    const o = canvas.fillStates.find(({ text }) => text === "o")!;
    const u = canvas.fillStates.find(({ text }) => text === "u")!;
    expect(y.x - k.x).toBe(10);
    expect(o.x - y.x).toBe(10);
    expect(u.x - o.x).toBe(18);
  });

  it("draws the sung shadow behind the sung outline", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, {
      lines: [{
        slot: "upper",
        text: "歌",
        units: [{
          text: "歌",
          progress: 0.5,
          characters: [{ text: "歌", progress: 0.5 }],
          ruby: [],
        }],
      }],
    }, {
      style: {
        ...DEFAULT_KIRAKARA_STYLE,
        strokeColorBefore: "#111111",
        strokeColorAfter: "#222222",
        shadowColor: "#333333",
        shadowDepth: 4,
      },
    });

    expect(canvas.strokeStates.slice(0, 2).map(({ strokeStyle }) => strokeStyle))
      .toEqual(["#333333", "#333333"]);
    expect(canvas.strokeStates.slice(2).map(({ strokeStyle }) => strokeStyle))
      .toContain("#222222");
    expect(canvas.fillText.mock.calls[0]).toEqual(["歌", 132, expect.any(Number)]);
  });
});
