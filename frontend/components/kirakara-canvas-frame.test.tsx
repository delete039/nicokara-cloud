/* @vitest-environment jsdom */

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_KIRAKARA_STYLE } from "@/lib/kirakara-style";

const { drawKirakaraFrame } = vi.hoisted(() => ({
  drawKirakaraFrame: vi.fn(),
}));
vi.mock("@/lib/kirakara-canvas", () => ({ drawKirakaraFrame }));

import { KirakaraCanvasFrame } from "./kirakara-canvas-frame";

describe("KirakaraCanvasFrame", () => {
  it("draws the current shared frame on a device-scaled design canvas", () => {
    const context = {} as CanvasRenderingContext2D;
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(context);
    const frame = {
      lines: [],
    } as never;

    const { container } = render(
      <KirakaraCanvasFrame frame={frame} style={DEFAULT_KIRAKARA_STYLE} />,
    );
    const canvas = container.querySelector("canvas");

    expect(canvas).not.toBeNull();
    expect(canvas?.width).toBe(1280);
    expect(canvas?.height).toBe(720);
    expect(drawKirakaraFrame).toHaveBeenCalledWith(
      context,
      frame,
      { style: DEFAULT_KIRAKARA_STYLE },
    );

    getContext.mockRestore();
  });
});
