"use client";

import { useLayoutEffect, useRef } from "react";

import { drawKirakaraFrame } from "@/lib/kirakara-canvas";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import type { KirakaraFrame } from "@/lib/kirakara-timeline";

const DESIGN_WIDTH = 1280;
const DESIGN_HEIGHT = 720;

function devicePixelRatio(): number {
  if (typeof window === "undefined") return 1;
  return Math.max(1, Math.min(2, window.devicePixelRatio || 1));
}

export function KirakaraCanvasFrame({
  frame,
  style,
}: {
  frame: KirakaraFrame | null;
  style: KirakaraStyle;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ratio = devicePixelRatio();
    canvas.width = Math.round(DESIGN_WIDTH * ratio);
    canvas.height = Math.round(DESIGN_HEIGHT * ratio);
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    drawKirakaraFrame(context, frame, { style });
  }, [frame, style]);

  return (
    <canvas
      ref={canvasRef}
      data-kirakara-canvas-preview="true"
      className="pointer-events-none absolute inset-0 size-full"
      aria-hidden="true"
    />
  );
}
