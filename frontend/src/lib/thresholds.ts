/**
 * Single source of truth for confidence / quality score thresholds and their
 * display colors.
 *
 * Before this module the 0.7 / 0.5 confidence bands and the 70 / 50 health
 * bands were re-declared as magic numbers in a dozen components, each with
 * slightly drifted boundary operators and null handling. Consolidating here
 * fixes the drift and gives every consumer one place to change the bands.
 *
 * **Standardized semantics** (applies to the helpers below and the band
 * classifiers): inclusive lower bound (`>=`) for each band, and
 * `null` / `undefined` / `NaN` → the "unknown" gray. Components that need a
 * different output format (border + background, a status dot, or a
 * `{bg,text,ring}` object) should import the **constants** and/or the band
 * classifier rather than re-hardcoding the numbers — see `GraphCanvas` and
 * `OntologyCard`. The confidence *lens* palette (`confidenceLensPalette.ts`)
 * is intentionally separate: it is a graph encoding, not a text badge.
 */

/** Confidence (0–1) is "high" at or above this. */
export const CONFIDENCE_HIGH = 0.7;
/** Confidence (0–1) is "medium" at or above this (below ⇒ "low"). */
export const CONFIDENCE_MEDIUM = 0.5;

/** Health / quality (0–100) is "high" at or above this. */
export const HEALTH_HIGH = 70;
/** Health / quality (0–100) is "medium" at or above this (below ⇒ "low"). */
export const HEALTH_MEDIUM = 50;

export type ScoreBand = "high" | "medium" | "low" | "unknown";

function isMissing(score: number | null | undefined): boolean {
  return score == null || Number.isNaN(score);
}

/** Classify a 0–1 confidence score into a band. */
export function confidenceBand(score: number | null | undefined): ScoreBand {
  if (isMissing(score)) return "unknown";
  const s = score as number;
  if (s >= CONFIDENCE_HIGH) return "high";
  if (s >= CONFIDENCE_MEDIUM) return "medium";
  return "low";
}

/** Classify a 0–100 health/quality score into a band. */
export function healthBand(score: number | null | undefined): ScoreBand {
  if (isMissing(score)) return "unknown";
  const s = score as number;
  if (s >= HEALTH_HIGH) return "high";
  if (s >= HEALTH_MEDIUM) return "medium";
  return "low";
}

const TEXT_COLOR: Record<ScoreBand, string> = {
  high: "text-green-600",
  medium: "text-yellow-600",
  low: "text-red-600",
  unknown: "text-gray-400",
};

const BG_COLOR: Record<ScoreBand, string> = {
  high: "bg-green-100",
  medium: "bg-yellow-100",
  low: "bg-red-100",
  unknown: "bg-gray-100",
};

/** Tailwind text-color class for a 0–1 confidence score. */
export function confidenceColor(score: number | null | undefined): string {
  return TEXT_COLOR[confidenceBand(score)];
}

/** Tailwind bg-color class for a 0–1 confidence score. */
export function confidenceBgColor(score: number | null | undefined): string {
  return BG_COLOR[confidenceBand(score)];
}

/** Tailwind text-color class for a 0–100 health/quality score. */
export function healthScoreColor(score: number | null | undefined): string {
  return TEXT_COLOR[healthBand(score)];
}
