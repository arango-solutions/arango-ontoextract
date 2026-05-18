/**
 * @jest-environment node
 *
 * Pure colour-math helpers for the imported-entity visual treatment
 * (Stream 1 H.15). The Sigma canvas, the React Flow canvas, and the
 * legend all consume the same constants from
 * ``importedEntityStyle.ts``; the tests below pin the contract so a
 * future tweak to ``IMPORTED_DIM_FACTOR`` (or the dimming math) is
 * caught immediately rather than silently shifting how every imported
 * node looks.
 */

import {
  IMPORTED_DIM_FACTOR,
  IMPORTED_NODE_BORDER,
  dimColorForImported,
} from "@/components/workspace/importedEntityStyle";

describe("importedEntityStyle", () => {
  describe("constants", () => {
    it("exposes a muted slate as the canonical imported border colour", () => {
      // Pinned because three modules (SigmaCanvas, BoxArrowCanvas,
      // CanvasLensLegend) reference this value and the legend describes
      // it verbatim to the user. Changing it is an intentional design
      // decision, not a refactor side-effect.
      expect(IMPORTED_NODE_BORDER).toBe("#94a3b8");
    });

    it("uses a 0.45 dim factor (default), leaving lens identity legible", () => {
      // Lower than 0.5 so the lens colour is still the dominant signal;
      // higher than 0.3 so the dimming is unambiguously visible on the
      // confidence lens where adjacent classes can have very close hues.
      expect(IMPORTED_DIM_FACTOR).toBeGreaterThan(0.3);
      expect(IMPORTED_DIM_FACTOR).toBeLessThan(0.6);
      expect(IMPORTED_DIM_FACTOR).toBe(0.45);
    });
  });

  describe("dimColorForImported", () => {
    it("returns the input unchanged when factor is 0", () => {
      // Pure mix identity — useful both as a sanity check and as the
      // "no dimming" fallback callers can pass when they want the helper
      // to be a no-op (e.g. snapshot tests).
      expect(dimColorForImported("#22c55e", 0)).toBe("#22c55e");
      expect(dimColorForImported("hsl(200, 82%, 70%)", 0)).toBe("hsl(200, 82%, 70%)");
    });

    it("returns pure slate-900 when factor is 1 on a hex input", () => {
      // The dim target is slate-900 (#1e293b). At factor=1 every input
      // collapses to the target colour. This anchors the upper bound of
      // the linear mix.
      expect(dimColorForImported("#22c55e", 1)).toBe("#1e293b");
      expect(dimColorForImported("#ffffff", 1)).toBe("#1e293b");
      expect(dimColorForImported("#000000", 1)).toBe("#1e293b");
    });

    it("interpolates linearly between the input and slate-900", () => {
      // Confidence-lens green (#22c55e = 34, 197, 94) mixed 55% toward
      // slate-900 (30, 41, 59) = (32, 111, 78) = #206f4e.
      // ``dimColorForImported`` exposes the math so the test can recompute
      // the expected output rather than hard-coding magic hex.
      const r = Math.round(0x22 * (1 - IMPORTED_DIM_FACTOR) + 0x1e * IMPORTED_DIM_FACTOR);
      const g = Math.round(0xc5 * (1 - IMPORTED_DIM_FACTOR) + 0x29 * IMPORTED_DIM_FACTOR);
      const b = Math.round(0x5e * (1 - IMPORTED_DIM_FACTOR) + 0x3b * IMPORTED_DIM_FACTOR);
      const hex = `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b
        .toString(16)
        .padStart(2, "0")}`;
      expect(dimColorForImported("#22c55e")).toBe(hex);
    });

    it("expands #rgb short-form before mixing", () => {
      // ``#fff`` is identical to ``#ffffff`` after expansion. The two
      // forms must produce the same dimmed output; otherwise the dim
      // treatment would silently differ for hex literals authored in
      // the short form vs the long form.
      expect(dimColorForImported("#fff", 0.5)).toBe(
        dimColorForImported("#ffffff", 0.5),
      );
    });

    it("dims HSL inputs by dropping saturation and lightness", () => {
      // Semantic lens emits ``hsl(H, 82%, 70%)`` for class fills. Dimming
      // drops S by ``factor * 25`` percentage points and L by ``factor *
      // 35``, clamped at 18% L. At the default factor (0.45):
      //   S: 82 - 0.45*25 = 70.75
      //   L: 70 - 0.45*35 = 54.25
      const result = dimColorForImported("hsl(200, 82%, 70%)");
      expect(result).toBe("hsl(200, 70.75%, 54.25%)");
    });

    it("clamps HSL lightness at 18% so dim never collapses fully", () => {
      // A very dark HSL input + factor=1 would dive negative without
      // the clamp. We pin the floor so highly-saturated low-L hues
      // (rare but possible) stay visible.
      const result = dimColorForImported("hsl(200, 50%, 30%)", 1);
      // L = max(18, 30 - 1*35) = max(18, -5) = 18.
      expect(result).toBe("hsl(200, 25%, 18%)");
    });

    it("returns unrecognised colour strings unchanged", () => {
      // Defensive: the renderer would rather show the wrong shade than
      // crash mid-paint. ``rgb()``, ``rgba()``, named colours, and bare
      // garbage all fall through to the identity branch.
      expect(dimColorForImported("rgb(255, 0, 0)")).toBe("rgb(255, 0, 0)");
      expect(dimColorForImported("not-a-color")).toBe("not-a-color");
      expect(dimColorForImported("")).toBe("");
    });

    it("returns hex strings with invalid digits unchanged", () => {
      // Defensive — bad hex (with non-hex characters past the leading #)
      // would parse to NaN. The helper detects that and returns the
      // input as-is rather than emitting "#NaNNaNNaN".
      expect(dimColorForImported("#zzzzzz")).toBe("#zzzzzz");
    });
  });
});
