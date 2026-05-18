/**
 * Visual encoding for entities that came from an imported ontology in the
 * effective-graph view (Stream 1 H.12 / H.15).
 *
 * Why a separate module
 * ---------------------
 *
 * Two canvases consume this:
 *
 *  * ``SigmaCanvas`` — Sigma (WebGL) draws nodes via ``color`` + ``borderColor``
 *    attributes on a ``graphology`` graph, so it needs the dimmed *colour* and
 *    the imported *border colour* as strings.
 *  * ``BoxArrowCanvas`` — React Flow draws ClassBoxNodes as React components,
 *    so it needs the same imported *border colour* but uses Tailwind ``opacity``
 *    + CSS ``border-style: dashed`` for the dim treatment (no canvas pixel
 *    blending needed there).
 *
 * Keeping the constants + the colour math here means the two renderers agree
 * on what "imported" looks like, and the legend (`CanvasLensLegend`) cites the
 * same hex when explaining the encoding to the user (workspace rule §12,
 * "every encoding is legible in-UI").
 *
 * Why not a CSS variable?
 *
 * Sigma's node program reads colour as a string attribute (the WebGL shader
 * does not know about CSS variables), so we need a literal string. Exporting
 * the same string for the React Flow path keeps the two visual treatments in
 * sync without a runtime lookup.
 */

/**
 * Border colour pinned on imported nodes regardless of active lens. A muted
 * slate that reads as "not currently owned" against every lens fill so the
 * imported signal beats the lens signal visually. Matches the slate used in
 * the legend swatch (`CanvasLensLegend`) so the legend explanation maps to
 * what the user sees on the canvas.
 */
export const IMPORTED_NODE_BORDER = "#94a3b8";

/**
 * Dim factor applied to lens colours when the entity is imported. ``0.45``
 * keeps roughly 55% of the original hue/saturation so the lens identity
 * stays legible (you can still see "this is a confidence-yellow node") while
 * the imported state dominates. Higher values wash everything out; lower
 * values defeat the purpose.
 */
export const IMPORTED_DIM_FACTOR = 0.45;

/** Slate-900 — neutral colour we mix *towards* when dimming. */
const DIM_TARGET_R = 0x1e;
const DIM_TARGET_G = 0x29;
const DIM_TARGET_B = 0x3b;

/**
 * Dim a CSS colour toward slate-900 by ``factor`` (0..1; default
 * {@link IMPORTED_DIM_FACTOR}). 0 returns the input untouched; 1 returns
 * pure slate. Supports the three forms produced by the workspace's lens
 * helpers:
 *
 *  * ``#rrggbb`` and ``#rgb`` — channel-wise linear mix
 *  * ``hsl(H, S%, L%)`` — drop S by ``factor * 25`` percentage points and
 *    L by ``factor * 35``, clamped at 18% L so saturation never fully
 *    collapses. The result is perceptually similar to the hex path.
 *  * any other string — returned unchanged (we'd rather show the wrong
 *    shade than crash the canvas mid-paint)
 *
 * The function is pure: callers can compose it freely and the unit tests
 * pin the output for every documented form.
 */
export function dimColorForImported(
  color: string,
  factor: number = IMPORTED_DIM_FACTOR,
): string {
  if (color.startsWith("#") && (color.length === 7 || color.length === 4)) {
    const isShort = color.length === 4;
    const expand = (c: string): string => (isShort ? `${c}${c}` : c);
    const r = parseInt(
      expand(color.slice(1, isShort ? 2 : 3)),
      16,
    );
    const g = parseInt(
      expand(color.slice(isShort ? 2 : 3, isShort ? 3 : 5)),
      16,
    );
    const b = parseInt(
      expand(color.slice(isShort ? 3 : 5, isShort ? 4 : 7)),
      16,
    );
    if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) return color;
    const mix = (a: number, t: number): number =>
      Math.round(a * (1 - factor) + t * factor);
    const out = (n: number): string => n.toString(16).padStart(2, "0");
    return `#${out(mix(r, DIM_TARGET_R))}${out(mix(g, DIM_TARGET_G))}${out(mix(b, DIM_TARGET_B))}`;
  }

  if (color.startsWith("hsl(")) {
    const m = /hsl\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)%\s*,\s*(-?\d+(?:\.\d+)?)%\s*\)/.exec(
      color,
    );
    if (!m) return color;
    const h = Number(m[1]);
    const s = Math.max(0, Number(m[2]) - factor * 25);
    const l = Math.max(18, Number(m[3]) - factor * 35);
    return `hsl(${h}, ${s}%, ${l}%)`;
  }

  return color;
}
