/**
 * Confidence lens thresholds (match CanvasLensLegend copy).
 */

/** Accept 0–1 or 0–100 (some APIs use percent). */
export function normalizeConfidence01(c: number): number {
  if (!Number.isFinite(c)) return 0.5;
  let x = c;
  if (x > 1.001) x = x / 100;
  return Math.min(1, Math.max(0, x));
}

export function confidenceNodeColor(confidence: number): string {
  const c = normalizeConfidence01(confidence);
  if (c > 0.7) return "#22c55e";
  if (c >= 0.5) return "#eab308";
  return "#ef4444";
}
