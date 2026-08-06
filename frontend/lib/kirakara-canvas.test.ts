import { describe, expect, it, vi } from "vitest";

import { drawKirakaraFrame } from "./kirakara-canvas";
import type { KirakaraFrame } from "./kirakara-timeline";

function context(
  measureText: (text: string, font: string) => number = (text) =>
    [...text].length * 40,
) {
  const canvasContext = {
    canvas: { width: 1280, height: 720 },
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    strokeText: vi.fn(),
    measureText: vi.fn((text: string) => ({
      width: measureText(text, canvasContext.font),
    })),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    font: "",
    textBaseline: "alphabetic" as CanvasTextBaseline,
    lineJoin: "round" as CanvasLineJoin,
    miterLimit: 2,
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

    expect(canvas.fillText).toHaveBeenCalledWith("今", 148.5, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("日", 197.5, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("歌", 1040.5, expect.any(Number));
    const upperCall = canvas.fillText.mock.calls.find(([text]) => text === "今");
    const lowerCall = canvas.fillText.mock.calls.find(([text]) => text === "歌");
    expect(upperCall?.[2]).toBeCloseTo(492.72, 2);
    expect(lowerCall?.[2]).toBeCloseTo(625.72, 2);
    expect(canvas.fillRect).not.toHaveBeenCalled();
  });

  it("draws ruby over kanji groups and clips sung progress", () => {
    const canvas = context();

    drawKirakaraFrame(canvas, frame);

    expect(canvas.fillText).toHaveBeenCalledWith("き", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("ょ", 173, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("う", 218, expect.any(Number));
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

  it("isolates ruby that is wider than its kanji and shifts following text", () => {
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

    expect(canvas.fillText).toHaveBeenCalledWith("火", 143, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("ほ", 128, expect.any(Number));
    expect(canvas.fillText).toHaveBeenCalledWith("山", 207, expect.any(Number));
  });
});
