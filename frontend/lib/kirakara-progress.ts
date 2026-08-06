export type InkAwareProgressInput = {
  rawProgress: number;
  fontSize: number;
  strokeWidth: number;
  width: number;
  inkLeft: number;
  inkRight: number;
  layoutWidth: number;
};

export function inkAwareProgress({
  rawProgress,
  fontSize,
  strokeWidth,
  width,
  inkLeft,
  inkRight,
  layoutWidth,
}: InkAwareProgressInput): {
  percentage: number;
  total: number;
  canvasWidth: number;
} {
  const progress = Math.min(1, Math.max(0, rawProgress));
  const emWidth = Math.max(width || fontSize, layoutWidth || fontSize);
  const total = emWidth + strokeWidth * 2;
  const strokeLeft = -inkLeft - 1;
  const strokeRight = inkRight + strokeWidth * 2 + 1;
  const clippedInk = strokeLeft + progress * (strokeRight - strokeLeft);

  return {
    percentage: clippedInk / total * 100,
    total,
    canvasWidth: fontSize - strokeWidth + clippedInk,
  };
}
