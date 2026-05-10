"use client";

/**
 * Canvas overlay slider that filters classes / edges by their confidence.
 *
 * Mirrors the VCR timeline as a *spatial* sibling at the bottom of the
 * canvas, but its filter axis is **confidence** instead of **time**. Its job
 * is to let the user answer "what would this ontology look like if I trusted
 * only entities at ≥ X% confidence?" — see the lens / data quality flow
 * called out in PRD §6.13 and the "every encoding is legible in-UI" rule
 * (workspace ``ui-architecture.mdc`` §12).
 *
 * The component is **only rendered when the active lens is ``confidence``**
 * (workspace rule §6: lens / graph style / layout are three different axes).
 * In every other lens the threshold has no visual meaning, so showing the
 * slider would invite the user to filter against an attribute the lens isn't
 * encoding.
 *
 * It does **not** mutate graph topology — it emits a ``Set<string>`` of class
 * keys that pass the threshold and lets the page intersect that with any
 * other ``visibleNodeKeys`` filter (e.g. the VCR timeline). The Sigma
 * ``nodeReducer`` then hides excluded nodes; positions and edges stay put,
 * so this is safe under workspace rule §14 ("lens change = paint, never
 * relayout") — the topology fingerprint of the underlying graph is
 * unchanged, only visibility flips.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { normalizeConfidence01 } from "@/components/workspace/confidenceLensPalette";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

/** Threshold values that get a tick mark + label. They match the bands the
 *  ``CanvasLensLegend`` already documents (High ≥ 70%, Medium 50–70%, Low <
 *  50%) so the slider's snap points are not new vocabulary. */
const TICK_PERCENTS: ReadonlyArray<number> = [0, 50, 70, 100];

export interface ConfidenceThresholdSliderProps {
  classes: OntologyClass[];
  edges: OntologyEdge[];
  /** Receives the set of *class* ``_key``s passing the threshold, or ``null``
   *  when the threshold is 0 (no filtering — equivalent to "off"). The page
   *  intersects this with any other visibility filter and hands the merged
   *  set to ``SigmaCanvas.visibleNodeKeys``. */
  onVisibleClassesChange: (visible: Set<string> | null) => void;
  /** Receives the set of *edge* ``_key``s passing the threshold (from
   *  ``edge.confidence`` populated by the backend's ``compute_edge_confidence``).
   *  ``null`` means "no filtering". Edges with no confidence are kept visible
   *  whenever the threshold is 0; once the threshold rises above 0 they are
   *  hidden so the lens stays internally consistent ("show only entities at
   *  ≥ X%" can't include entities we never measured). */
  onVisibleEdgesChange: (visible: Set<string> | null) => void;
}

export default function ConfidenceThresholdSlider({
  classes,
  edges,
  onVisibleClassesChange,
  onVisibleEdgesChange,
}: ConfidenceThresholdSliderProps) {
  const [thresholdPct, setThresholdPct] = useState<number>(0);

  /** Pre-compute the per-class confidence (already in [0, 1] thanks to
   *  ``normalizeConfidence01``) once per ``classes`` change so the slider
   *  drag stays cheap on large ontologies. */
  const classConfidence = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of classes) {
      m.set(c._key, normalizeConfidence01(c.confidence ?? 0));
    }
    return m;
  }, [classes]);

  /** Same for edges. ``edge.confidence`` may be undefined when the edge has
   *  no evidence — we record that as ``null`` (distinct from 0) so the
   *  filter logic can treat "unknown" differently from "measured zero". */
  const edgeConfidence = useMemo(() => {
    const m = new Map<string, number | null>();
    for (const e of edges) {
      const c = e.confidence;
      m.set(
        e._key,
        c == null || Number.isNaN(c) ? null : normalizeConfidence01(c),
      );
    }
    return m;
  }, [edges]);

  const threshold01 = thresholdPct / 100;

  /** Recompute and emit visible sets whenever the threshold or the input
   *  data changes. We emit ``null`` at threshold 0 so consumers can short-
   *  circuit and skip the intersection cost when filtering is "off". */
  useEffect(() => {
    if (thresholdPct === 0) {
      onVisibleClassesChange(null);
      onVisibleEdgesChange(null);
      return;
    }
    const visibleClasses = new Set<string>();
    classConfidence.forEach((conf, key) => {
      if (conf >= threshold01) visibleClasses.add(key);
    });
    const visibleEdges = new Set<string>();
    edgeConfidence.forEach((conf, key) => {
      if (conf != null && conf >= threshold01) visibleEdges.add(key);
    });
    onVisibleClassesChange(visibleClasses);
    onVisibleEdgesChange(visibleEdges);
  }, [
    thresholdPct,
    threshold01,
    classConfidence,
    edgeConfidence,
    onVisibleClassesChange,
    onVisibleEdgesChange,
  ]);

  /** Reset to "everything visible" when the slider unmounts (lens switch).
   *  Without this, switching from Confidence → Semantic would leave the
   *  page's visible-keys state set to the last threshold. */
  useEffect(() => {
    return () => {
      onVisibleClassesChange(null);
      onVisibleEdgesChange(null);
    };
  }, [onVisibleClassesChange, onVisibleEdgesChange]);

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setThresholdPct(parseInt(e.target.value, 10));
    },
    [],
  );

  const handleReset = useCallback(() => {
    setThresholdPct(0);
  }, []);

  const handleTickClick = useCallback((pct: number) => {
    setThresholdPct(pct);
  }, []);

  /** Live counts for the "Showing N of M" readout. We compute these on the
   *  fly rather than reading them out of the visible sets we just emitted
   *  because the emitted sets collapse to ``null`` at threshold 0 — the
   *  readout still wants to show "M of M" in that case. */
  const totalClasses = classes.length;
  const totalEdges = edges.length;
  const visibleClassCount = useMemo(() => {
    if (thresholdPct === 0) return totalClasses;
    let n = 0;
    classConfidence.forEach((conf) => {
      if (conf >= threshold01) n += 1;
    });
    return n;
  }, [thresholdPct, threshold01, classConfidence, totalClasses]);
  const visibleEdgeCount = useMemo(() => {
    if (thresholdPct === 0) return totalEdges;
    let n = 0;
    edgeConfidence.forEach((conf) => {
      if (conf != null && conf >= threshold01) n += 1;
    });
    return n;
  }, [thresholdPct, threshold01, edgeConfidence, totalEdges]);

  const edgesWithoutConfidence = useMemo(() => {
    let n = 0;
    edgeConfidence.forEach((conf) => {
      if (conf == null) n += 1;
    });
    return n;
  }, [edgeConfidence]);

  return (
    <div
      className="space-y-2"
      data-testid="confidence-threshold-slider"
      role="group"
      aria-label="Confidence threshold filter"
    >
      <div className="flex items-center gap-3 text-xs text-gray-300">
        <span className="font-semibold uppercase tracking-wide text-indigo-200/90">
          Confidence ≥
        </span>
        <span
          className="font-mono text-sm text-indigo-100 tabular-nums w-12 text-right"
          data-testid="confidence-threshold-value"
        >
          {thresholdPct}%
        </span>
        <button
          type="button"
          onClick={handleReset}
          disabled={thresholdPct === 0}
          className="px-2 py-0.5 text-[10px] rounded border border-gray-600 text-gray-300 hover:border-indigo-400 hover:text-indigo-200 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Reset threshold to 0"
          data-testid="confidence-threshold-reset"
        >
          Reset
        </button>
        <div
          className="ml-auto text-[10px] text-gray-400 tabular-nums"
          data-testid="confidence-threshold-counts"
          aria-live="polite"
        >
          Showing {visibleClassCount} of {totalClasses} classes ·{" "}
          {visibleEdgeCount} of {totalEdges} edges
          {edgesWithoutConfidence > 0 && thresholdPct > 0 && (
            <span className="ml-1 text-amber-400/80">
              ({edgesWithoutConfidence} edge
              {edgesWithoutConfidence === 1 ? "" : "s"} have no confidence and
              are hidden above 0%)
            </span>
          )}
        </div>
      </div>
      <div className="relative">
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={thresholdPct}
          onChange={handleSliderChange}
          className="w-full accent-indigo-400"
          aria-label="Confidence threshold percent"
          data-testid="confidence-threshold-input"
        />
        <div className="relative h-3 mt-1">
          {TICK_PERCENTS.map((pct) => (
            <button
              key={pct}
              type="button"
              onClick={() => handleTickClick(pct)}
              className="absolute top-0 -translate-x-1/2 text-[9px] text-gray-400 hover:text-indigo-300 cursor-pointer"
              style={{ left: `${pct}%` }}
              title={`Snap to ${pct}%`}
              data-testid={`confidence-threshold-tick-${pct}`}
            >
              <span aria-hidden="true">|</span>
              <span className="block">{pct}%</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
