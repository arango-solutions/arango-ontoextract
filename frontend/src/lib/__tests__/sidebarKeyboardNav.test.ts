import { computeNextSidebarRow } from "../sidebarKeyboardNav";

/**
 * Tests for the W.7 (Stream 10) sidebar arrow-key navigation helper.
 *
 * The page-level wiring lives in `app/workspace/page.tsx`'s
 * keydown effect; this suite covers the pure decision atom in
 * isolation so a future regression -- wrap-around, skipping a row,
 * stealing focus on unrelated keys, etc. -- is caught here without
 * needing to mount the full workspace.
 */

function makeRow(id: string): HTMLElement {
  const el = document.createElement("button");
  el.setAttribute("data-sidebar-row", id);
  el.textContent = id;
  return el;
}

describe("computeNextSidebarRow", () => {
  it("moves focus down by one on ArrowDown", () => {
    const rows = [makeRow("a"), makeRow("b"), makeRow("c")];
    const next = computeNextSidebarRow("ArrowDown", rows[0], rows);
    expect(next).toBe(rows[1]);
  });

  it("moves focus up by one on ArrowUp", () => {
    const rows = [makeRow("a"), makeRow("b"), makeRow("c")];
    const next = computeNextSidebarRow("ArrowUp", rows[2], rows);
    expect(next).toBe(rows[1]);
  });

  it("clamps at the bottom (no wrap-around)", () => {
    const rows = [makeRow("a"), makeRow("b"), makeRow("c")];
    const next = computeNextSidebarRow("ArrowDown", rows[2], rows);
    expect(next).toBeNull();
  });

  it("clamps at the top (no wrap-around)", () => {
    const rows = [makeRow("a"), makeRow("b"), makeRow("c")];
    const next = computeNextSidebarRow("ArrowUp", rows[0], rows);
    expect(next).toBeNull();
  });

  it("ignores non-arrow keys", () => {
    const rows = [makeRow("a"), makeRow("b")];
    expect(computeNextSidebarRow("Enter", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("Tab", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("Escape", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("a", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("ArrowLeft", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("ArrowRight", rows[0], rows)).toBeNull();
  });

  it("returns null when the current row is not in the list", () => {
    const rows = [makeRow("a"), makeRow("b")];
    const orphan = makeRow("orphan");
    expect(computeNextSidebarRow("ArrowDown", orphan, rows)).toBeNull();
  });

  it("returns null when there are no rows", () => {
    const orphan = makeRow("solo");
    expect(computeNextSidebarRow("ArrowDown", orphan, [])).toBeNull();
  });

  it("works on a single-element list (clamps both directions)", () => {
    const rows = [makeRow("only")];
    expect(computeNextSidebarRow("ArrowDown", rows[0], rows)).toBeNull();
    expect(computeNextSidebarRow("ArrowUp", rows[0], rows)).toBeNull();
  });

  it("respects DOM order in the supplied list (not insertion order)", () => {
    // Simulates the asset explorer where collapsed ontologies omit
    // their classes, so the visible-rows list is a filtered subset.
    const a = makeRow("class:o1:a");
    const c = makeRow("class:o1:c");
    const e = makeRow("class:o2:e");
    const rows = [a, c, e];
    expect(computeNextSidebarRow("ArrowDown", a, rows)).toBe(c);
    expect(computeNextSidebarRow("ArrowDown", c, rows)).toBe(e);
    expect(computeNextSidebarRow("ArrowUp", e, rows)).toBe(c);
    expect(computeNextSidebarRow("ArrowUp", c, rows)).toBe(a);
  });
});
