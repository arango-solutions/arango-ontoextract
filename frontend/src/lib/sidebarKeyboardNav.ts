/**
 * W.7 (Stream 10) -- pure helper for the workspace page's
 * ArrowUp / ArrowDown navigation across `[data-sidebar-row]` buttons
 * in the asset explorer.
 *
 * Extracted from `app/workspace/page.tsx`'s `handleKeyDown` so the
 * decision logic can be unit-tested in isolation (the page-level
 * effect that actually wires this to `window` is harder to test in
 * jsdom without mounting half the workspace).
 *
 * Contract:
 *   * Returns the element that should receive focus, or `null` if the
 *     event should be ignored (wrong key, no current row, already at
 *     the boundary).
 *   * Caller is responsible for calling `.focus()` on the returned
 *     element and `preventDefault()`-ing the original event so the
 *     browser does not also scroll the page.
 *   * Navigation is clamped (no wrap-around) -- the visual mental
 *     model is a linear list; wrapping would surprise users when the
 *     explorer has thousands of rows.
 */
export function computeNextSidebarRow(
  key: string,
  currentRow: HTMLElement,
  allRows: HTMLElement[],
): HTMLElement | null {
  if (key !== "ArrowDown" && key !== "ArrowUp") return null;
  if (allRows.length === 0) return null;
  const idx = allRows.indexOf(currentRow);
  if (idx < 0) return null;
  const next =
    key === "ArrowDown"
      ? Math.min(allRows.length - 1, idx + 1)
      : Math.max(0, idx - 1);
  if (next === idx) return null;
  return allRows[next];
}
