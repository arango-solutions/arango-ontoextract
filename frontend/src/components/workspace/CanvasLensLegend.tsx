"use client";

import {
  ONTOLOGY_EDGE_COLORS,
  SEMANTIC_EDGE_LEGEND,
} from "@/components/graph/graphVisualPalette";
import type { LensType } from "@/components/workspace/LensToolbar";

export interface CanvasLensLegendProps {
  activeLens: LensType;
  /** When set, diff lens is showing a timeline-filtered subgraph */
  timelineActive: boolean;
}

const SEMANTIC_SWATCHES: { color: string; label: string }[] = [
  {
    color: "hsl(200, 82%, 70%)",
    label: "Classes — bright hue from URI (OWL types use fixed accent colors)",
  },
  ...SEMANTIC_EDGE_LEGEND.map(({ edgeType, label }) => ({
    color: ONTOLOGY_EDGE_COLORS[edgeType] ?? "#cbd5e1",
    label: `Edge — ${label}`,
  })),
];

const LENS_META: Record<
  LensType,
  { headline: string; swatches: { color: string; label: string }[]; note?: string }
> = {
  semantic: {
    headline: "Semantic",
    swatches: SEMANTIC_SWATCHES,
    note: "Node diameter scales with PageRank (degree fallback). Edge colors are chosen to read clearly on a dark canvas. Curation is hidden — use the Curation Status lens.",
  },
  confidence: {
    headline: "Confidence",
    swatches: [
      { color: "#22c55e", label: "High (≥70%)" },
      { color: "#eab308", label: "Medium (50–70%)" },
      { color: "#ef4444", label: "Low (below 50%)" },
    ],
    note: "Fill and size reflect class confidence; labels append a % when known. Edges use confidence color/thickness when per-edge confidence exists; otherwise they keep relation-type colors.",
  },
  curation: {
    headline: "Curation status",
    swatches: [
      { color: "#22c55e", label: "Approved" },
      { color: "#f59e0b", label: "Pending" },
      { color: "#ef4444", label: "Rejected" },
    ],
    note: "Ring and fill show review state for classes and edges (when status exists). Node diameter is not approval — it matches structural importance (PageRank on the class graph, degree fallback), same as Semantic / Source / Diff.",
  },
  diff: {
    headline: "Diff (vs timeline)",
    swatches: [
      { color: "#34d399", label: "Entities visible at scrubbed time" },
      { color: "#64748b", label: "Hidden / not in snapshot (when filter on)" },
    ],
    note: "Switching lenses does not re-run layout. Scrubbing the timeline changes which nodes exist — that can re-layout because the graph topology changes.",
  },
  source: {
    headline: "Source type",
    swatches: [
      { color: "#2dd4bf", label: "Domain tier" },
      { color: "#fbbf24", label: "Local / extension tier" },
      { color: "#94a3b8", label: "Unknown / other" },
    ],
    note: "Per-class tier when present; otherwise the ontology’s library tier is used. Grey means neither was available.",
  },
};

export default function CanvasLensLegend({
  activeLens,
  timelineActive,
}: CanvasLensLegendProps) {
  const meta = LENS_META[activeLens];
  const note =
    activeLens === "diff" && timelineActive
      ? "Timeline filter is on — green nodes are in the snapshot at the scrubbed time."
      : meta.note;

  return (
    <div
      className="absolute bottom-12 left-3 z-20 max-w-[min(300px,calc(100vw-1.5rem))] rounded-lg border border-white/10 bg-black/55 px-3 py-2 text-left shadow-lg backdrop-blur-sm pointer-events-none"
      data-testid="canvas-lens-legend"
      aria-live="polite"
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide text-indigo-200/90">
        View: {meta.headline}
      </div>
      <ul className="mt-1.5 space-y-1">
        {meta.swatches.map((s) => (
          <li key={s.label} className="flex items-center gap-2 text-[10px] text-gray-200">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/20"
              style={{ backgroundColor: s.color }}
            />
            <span>{s.label}</span>
          </li>
        ))}
      </ul>
      {note && (
        <p className="mt-2 text-[9px] leading-snug text-gray-400 border-t border-white/10 pt-2">
          {note}
        </p>
      )}
    </div>
  );
}
