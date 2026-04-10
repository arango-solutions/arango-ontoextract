import {
  clampPanelToViewport,
  computeInitialPanelPosition,
} from "@/hooks/useDraggablePanel";

describe("clampPanelToViewport", () => {
  it("keeps panel inside viewport horizontally", () => {
    expect(clampPanelToViewport(0, 20, 360, 800, 600)).toEqual({
      left: 12,
      top: 20,
    });
    expect(clampPanelToViewport(900, 20, 360, 800, 600)).toEqual({
      left: 428,
      top: 20,
    });
  });

  it("clamps vertical position", () => {
    expect(clampPanelToViewport(100, -50, 360, 800, 600).top).toBe(12);
    // vh 600 → maxTop 500
    expect(clampPanelToViewport(100, 9999, 360, 800, 600).top).toBe(500);
  });
});

describe("computeInitialPanelPosition", () => {
  const vw = 1200;
  const vh = 800;
  const w = 360;

  it("places viewportTopRight near the right edge", () => {
    const p = computeInitialPanelPosition(w, vw, vh, { placement: "viewportTopRight" });
    expect(p.left).toBeGreaterThan(vw / 2);
  });

  it("places mainColumnTopLeft after the explorer inset", () => {
    const inset = 280;
    const p = computeInitialPanelPosition(w, vw, vh, {
      placement: "mainColumnTopLeft",
      mainColumnLeftInset: inset,
    });
    expect(p.left).toBeLessThan(vw / 2);
    expect(p.left).toBeGreaterThanOrEqual(inset + 12);
  });

  it("offsets stacked panels diagonally", () => {
    const a = computeInitialPanelPosition(w, vw, vh, { placement: "viewportTopRight", stackIndex: 0 });
    const b = computeInitialPanelPosition(w, vw, vh, { placement: "viewportTopRight", stackIndex: 1 });
    expect(b.left).toBeLessThan(a.left);
    expect(b.top).toBeGreaterThan(a.top);
  });
});
