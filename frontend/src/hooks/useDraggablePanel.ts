"use client";

import { useCallback, useRef, useState } from "react";

const VIEW_MARGIN = 12;
/** Keep enough vertical room that the drag header can stay reachable. */
const VIEW_BOTTOM_RESERVE = 100;
/** Below workspace top bar (LensToolbar ~44px + gap). */
const TOP_BELOW_APP_HEADER = 56;
/** Diagonal offset when stacking multiple panels with the same placement. */
const STACK_STEP = 32;

export type DraggablePanelPlacement = "viewportTopRight" | "mainColumnTopLeft";

export interface UseDraggablePanelOptions {
  /**
   * Where the panel first appears. Use different placements for overlays that
   * often open together (e.g. class detail vs asset info) so they do not spawn
   * on top of each other.
   */
  placement?: DraggablePanelPlacement;
  /** For `mainColumnTopLeft`: pixels from left edge of viewport to main canvas (explorer + separator). */
  mainColumnLeftInset?: number;
  /** Same-placement stacking index (0 = primary position). */
  stackIndex?: number;
}

export function clampPanelToViewport(
  left: number,
  top: number,
  panelWidth: number,
  vw: number,
  vh: number,
): { left: number; top: number } {
  const maxLeft = Math.max(VIEW_MARGIN, vw - panelWidth - VIEW_MARGIN);
  const maxTop = Math.max(VIEW_MARGIN, vh - VIEW_BOTTOM_RESERVE);
  return {
    left: Math.min(Math.max(VIEW_MARGIN, left), maxLeft),
    top: Math.min(Math.max(VIEW_MARGIN, top), maxTop),
  };
}

/** Exported for unit tests — computes first paint position before clamping. */
export function computeInitialPanelPosition(
  panelWidth: number,
  vw: number,
  vh: number,
  options: UseDraggablePanelOptions = {},
): { left: number; top: number } {
  const stack = options.stackIndex ?? 0;
  const step = STACK_STEP * stack;
  const placement = options.placement ?? "viewportTopRight";

  if (placement === "mainColumnTopLeft") {
    const inset = options.mainColumnLeftInset ?? 0;
    const left = inset + VIEW_MARGIN + step;
    const top = TOP_BELOW_APP_HEADER + step;
    return clampPanelToViewport(left, top, panelWidth, vw, vh);
  }

  const left = vw - panelWidth - VIEW_MARGIN - step;
  const top = TOP_BELOW_APP_HEADER + step;
  return clampPanelToViewport(left, top, panelWidth, vw, vh);
}

function initialFromWindow(panelWidth: number, options: UseDraggablePanelOptions): {
  left: number;
  top: number;
} {
  if (typeof window === "undefined") {
    return { left: VIEW_MARGIN, top: VIEW_MARGIN };
  }
  return computeInitialPanelPosition(
    panelWidth,
    window.innerWidth,
    window.innerHeight,
    options,
  );
}

type DragState = {
  pointerId: number;
  startX: number;
  startY: number;
  origLeft: number;
  origTop: number;
};

const BASE_Z = 50;
const DRAG_Z = 220;

/**
 * Fixed-position overlay panels that can be dragged by the header (viewport coords).
 */
export function useDraggablePanel(
  panelWidth: number,
  options: UseDraggablePanelOptions = {},
) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(() => initialFromWindow(panelWidth, options));
  const [isDragging, setIsDragging] = useState(false);
  const drag = useRef<DragState | null>(null);

  const onHeaderPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      const panel = panelRef.current;
      if (!panel) return;
      const r = panel.getBoundingClientRect();
      setIsDragging(true);
      drag.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        origLeft: r.left,
        origTop: r.top,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [],
  );

  const onHeaderPointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!drag.current || e.pointerId !== drag.current.pointerId) return;
      const { startX, startY, origLeft, origTop } = drag.current;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const nextLeft = origLeft + dx;
      const nextTop = origTop + dy;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      setPosition(clampPanelToViewport(nextLeft, nextTop, panelWidth, vw, vh));
    },
    [panelWidth],
  );

  const endDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!drag.current || e.pointerId !== drag.current.pointerId) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    drag.current = null;
    setIsDragging(false);
  }, []);

  const panelStyle: React.CSSProperties = {
    position: "fixed",
    left: position.left,
    top: position.top,
    width: panelWidth,
    zIndex: isDragging ? DRAG_Z : BASE_Z,
  };

  const dragHandleProps = {
    onPointerDown: onHeaderPointerDown,
    onPointerMove: onHeaderPointerMove,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    className: "cursor-grab active:cursor-grabbing select-none touch-none",
    role: "toolbar" as const,
    "aria-label": "Drag to move panel",
    title: "Drag header to move",
  };

  return { panelRef, panelStyle, dragHandleProps };
}
