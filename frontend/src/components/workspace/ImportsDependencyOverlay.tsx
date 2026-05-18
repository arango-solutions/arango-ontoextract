"use client";

/**
 * Imports Dependency overlay (Stream 1 H.7).
 *
 * DAG canvas of the ``owl:imports`` neighbourhood of a single ontology.
 * Sourced from ``GET /api/v1/ontology/imports-graph?root=<key>``
 * (Stream 1 H.3) which returns ancestors + dependents in one pass.
 *
 * Layout: layered Sugiyama-style columns. Outbound (what the root
 * imports) is placed to the right; inbound (who imports the root) is
 * placed to the left. The root is centred. BFS from the root assigns
 * each node a layer index; within a layer nodes are stacked vertically
 * in first-seen order so the layout is stable across refreshes
 * (deterministic data + deterministic layout = no flicker).
 *
 * Interaction:
 *  - Left-click a non-root node → re-roots the DAG on that node (per
 *    ``ui-architecture.mdc`` left-click-selects rule; this is a safe
 *    read-only operation).
 *  - "Open in canvas" button on the floating detail of the selected
 *    node → switches the workspace selection and closes the overlay.
 *  - Esc / × → close.
 *
 * Why a hand-rolled SVG instead of sigma/cytoscape: the DAGs we care
 * about are tiny (almost always < 30 nodes). Pulling sigma into an
 * overlay would add ~250 KB to the workspace bundle for a feature that
 * a 250-line component handles correctly. If we ever need pan/zoom
 * for >30 nodes we can swap implementations behind the same props.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api-client";

export interface ImportsGraphNode {
  _key: string;
  name?: string | null;
  status?: string | null;
  tier?: string | null;
}

export interface ImportsGraphEdge {
  edge_key: string;
  from_key: string;
  to_key: string;
  import_iri?: string | null;
  created?: string | null;
}

interface ImportsGraphResponse {
  nodes: ImportsGraphNode[];
  edges: ImportsGraphEdge[];
  root?: string | null;
  direction?: string | null;
  truncated?: boolean;
}

interface Props {
  ontologyId: string;
  ontologyName: string;
  /** Optional: max traversal depth, surfaced as a dropdown. Defaults to 5
   *  -- the deepest production import chain we've seen is 4 (PROV-O
   *  imports DC Terms imports DC Elements imports XML Schema). */
  initialDepth?: number;
  onClose: () => void;
  /** Fired when the user clicks "Open in workspace" on a selected node.
   *  The parent should switch the workspace ontology and (typically)
   *  close the overlay. */
  onNavigate: (ontologyId: string, ontologyName: string) => void;
}

interface LayoutNode extends ImportsGraphNode {
  layer: number;
  /** Vertical slot within the layer (0..N-1). */
  slot: number;
  /** Pixel position assigned by ``layout()``. */
  x: number;
  y: number;
}

const NODE_W = 168;
const NODE_H = 52;
const LAYER_GAP = 64;
const ROW_GAP = 18;
const SVG_PAD = 32;

export default function ImportsDependencyOverlay({
  ontologyId: initialOntologyId,
  ontologyName: initialOntologyName,
  initialDepth = 5,
  onClose,
  onNavigate,
}: Props) {
  // Re-rooting (the overlay can pivot to any clicked node) means we
  // track our own "current root" state, seeded by the props.
  const [rootKey, setRootKey] = useState(initialOntologyId);
  const [rootName, setRootName] = useState(initialOntologyName);
  const [depth, setDepth] = useState(initialDepth);

  const [graph, setGraph] = useState<ImportsGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setGraph(null);
    setSelectedKey(null);
    const url =
      `/api/v1/ontology/imports-graph?root=${encodeURIComponent(rootKey)}` +
      `&direction=both&max_depth=${depth}`;
    api
      .get<ImportsGraphResponse>(url)
      .then((res) => {
        if (cancelled) return;
        setGraph(res);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.body.message
            : "Failed to load dependency graph";
        setLoadError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [rootKey, depth]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const layout = useMemo(() => computeLayout(graph, rootKey), [graph, rootKey]);

  const handleRecenter = useCallback(
    (node: ImportsGraphNode) => {
      if (node._key === rootKey) {
        setSelectedKey(node._key);
        return;
      }
      setRootKey(node._key);
      setRootName(node.name ?? node._key);
    },
    [rootKey],
  );

  const selectedNode =
    (selectedKey && layout.nodes.find((n) => n._key === selectedKey)) || null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="imports-dep-title"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[860px] max-h-[88vh] flex flex-col">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close dependency graph"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 id="imports-dep-title" className="text-lg font-semibold text-gray-900">
            Dependency Graph
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            <span className="font-medium text-gray-700">{rootName}</span> and its
            <span className="mx-1 inline-block px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 text-[10px]">
              imports
            </span>
            ancestors + dependents (live{" "}
            <span className="font-mono text-xs">owl:imports</span> edges, depth ≤{" "}
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="border border-gray-200 rounded px-1 py-0.5 text-xs"
              aria-label="Max traversal depth"
            >
              {[1, 2, 3, 5, 10].map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            ).
          </p>
        </div>

        <div className="flex-1 overflow-auto bg-gradient-to-br from-slate-50 to-slate-100 relative">
          {loading && <SpinnerOverlay />}
          {loadError && (
            <div className="m-6 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
              {loadError}
            </div>
          )}
          {!loading && !loadError && layout.nodes.length <= 1 && (
            <EmptyState rootName={rootName} />
          )}
          {!loading && !loadError && layout.nodes.length > 1 && (
            <DagSvg
              layout={layout}
              rootKey={rootKey}
              selectedKey={selectedKey}
              onSelect={(node) => setSelectedKey(node._key)}
              onRecenter={handleRecenter}
            />
          )}
        </div>

        <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between gap-3">
          <div className="text-xs text-gray-500 flex items-center gap-3">
            <Legend swatch="bg-indigo-500" label="root" />
            <Legend swatch="bg-blue-300" label="ancestors (imports)" />
            <Legend swatch="bg-emerald-300" label="dependents (imported by)" />
            {graph?.truncated && (
              <span className="text-amber-600">
                ⚠ truncated at depth {depth}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            {selectedNode && selectedNode._key !== initialOntologyId && (
              <button
                type="button"
                onClick={() => onNavigate(selectedNode._key, selectedNode.name ?? selectedNode._key)}
                className="text-xs font-medium px-3 py-1.5 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
              >
                Open in workspace
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-xs font-medium px-3 py-1.5 bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface Layout {
  nodes: LayoutNode[];
  edges: ImportsGraphEdge[];
  width: number;
  height: number;
}

/** Compute a stable layered layout. Pure of React; tested independently. */
export function computeLayout(
  graph: ImportsGraphResponse | null,
  rootKey: string,
): Layout {
  if (!graph || graph.nodes.length === 0) {
    return { nodes: [], edges: [], width: 320, height: 120 };
  }

  const nodeMap = new Map<string, ImportsGraphNode>();
  graph.nodes.forEach((n) => nodeMap.set(n._key, n));

  // Build adjacency lists keyed on node -> [outgoing, incoming] arrays.
  const out = new Map<string, string[]>();
  const inc = new Map<string, string[]>();
  graph.edges.forEach((e) => {
    if (!out.has(e.from_key)) out.set(e.from_key, []);
    out.get(e.from_key)!.push(e.to_key);
    if (!inc.has(e.to_key)) inc.set(e.to_key, []);
    inc.get(e.to_key)!.push(e.from_key);
  });

  // BFS outbound (positive layers) and inbound (negative layers) so the
  // root is at layer 0 in the middle. Truncate at depth 10 defensively;
  // the backend already clamps to <= 50 but we don't want a runaway
  // browser loop if a cycle slips through.
  const layer = new Map<string, number>();
  layer.set(rootKey, 0);
  const order: string[] = [rootKey];

  const bfs = (seed: string, follow: Map<string, string[]>, sign: 1 | -1) => {
    const queue: string[] = [seed];
    while (queue.length) {
      const k = queue.shift()!;
      const next = follow.get(k) ?? [];
      for (const nxt of next) {
        if (layer.has(nxt)) continue;
        if (!nodeMap.has(nxt)) continue;
        const nextLayer = (layer.get(k) ?? 0) + sign;
        if (Math.abs(nextLayer) > 10) continue;
        layer.set(nxt, nextLayer);
        order.push(nxt);
        queue.push(nxt);
      }
    }
  };

  bfs(rootKey, out, 1);
  bfs(rootKey, inc, -1);

  // Orphan nodes (present in graph.nodes but unreachable from root via
  // either direction) get placed in a far-right "unrelated" column so
  // the user knows the registry returned them but they aren't connected
  // to this root. In practice this only happens when the backend
  // direction != "both" query was issued, which we don't do today.
  graph.nodes.forEach((n) => {
    if (!layer.has(n._key)) {
      layer.set(n._key, 99);
      order.push(n._key);
    }
  });

  // Group by layer, preserving first-seen order within each layer so the
  // layout doesn't flicker between refreshes (the API already sorts
  // both arrays).
  const byLayer = new Map<number, string[]>();
  order.forEach((k) => {
    const l = layer.get(k)!;
    if (!byLayer.has(l)) byLayer.set(l, []);
    byLayer.get(l)!.push(k);
  });

  const layerIndices = Array.from(byLayer.keys()).sort((a, b) => a - b);
  const tallestColumn = Math.max(...Array.from(byLayer.values()).map((l) => l.length));
  const height = SVG_PAD * 2 + tallestColumn * NODE_H + (tallestColumn - 1) * ROW_GAP;
  const width = SVG_PAD * 2 + layerIndices.length * NODE_W + (layerIndices.length - 1) * LAYER_GAP;

  const nodes: LayoutNode[] = [];
  layerIndices.forEach((l, columnIdx) => {
    const keys = byLayer.get(l)!;
    const columnX = SVG_PAD + columnIdx * (NODE_W + LAYER_GAP);
    const columnHeight = keys.length * NODE_H + (keys.length - 1) * ROW_GAP;
    const yOffset = (height - columnHeight) / 2;
    keys.forEach((k, slot) => {
      const base = nodeMap.get(k)!;
      nodes.push({
        ...base,
        layer: l,
        slot,
        x: columnX,
        y: yOffset + slot * (NODE_H + ROW_GAP),
      });
    });
  });

  return { nodes, edges: graph.edges, width, height };
}

function DagSvg({
  layout,
  rootKey,
  selectedKey,
  onSelect,
  onRecenter,
}: {
  layout: Layout;
  rootKey: string;
  selectedKey: string | null;
  onSelect: (n: ImportsGraphNode) => void;
  onRecenter: (n: ImportsGraphNode) => void;
}) {
  const nodeIdx = new Map<string, LayoutNode>();
  layout.nodes.forEach((n) => nodeIdx.set(n._key, n));

  return (
    <svg
      width={layout.width}
      height={layout.height}
      role="img"
      aria-label="Ontology imports dependency graph"
      className="block mx-auto my-6"
    >
      <defs>
        <marker
          id="dep-arrow"
          viewBox="0 0 10 10"
          refX="10"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
        </marker>
      </defs>

      {layout.edges.map((e) => {
        const from = nodeIdx.get(e.from_key);
        const to = nodeIdx.get(e.to_key);
        if (!from || !to) return null;
        const x1 = from.x + NODE_W;
        const y1 = from.y + NODE_H / 2;
        const x2 = to.x;
        const y2 = to.y + NODE_H / 2;
        return (
          <line
            key={e.edge_key}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke="#94a3b8"
            strokeWidth={1.5}
            markerEnd="url(#dep-arrow)"
            opacity={0.7}
          />
        );
      })}

      {layout.nodes.map((n) => {
        const isRoot = n._key === rootKey;
        const isSelected = n._key === selectedKey;
        const fill = isRoot
          ? "#6366f1"
          : n.layer < 0
            ? "#bfdbfe"
            : n.layer > 0 && n.layer < 99
              ? "#a7f3d0"
              : "#e5e7eb";
        const textColor = isRoot ? "#ffffff" : "#111827";

        return (
          <g
            key={n._key}
            transform={`translate(${n.x}, ${n.y})`}
            onClick={() => onSelect(n)}
            onDoubleClick={() => onRecenter(n)}
            style={{ cursor: "pointer" }}
            data-testid={`dep-node-${n._key}`}
          >
            <rect
              width={NODE_W}
              height={NODE_H}
              rx={8}
              ry={8}
              fill={fill}
              stroke={isSelected ? "#1e293b" : "#cbd5e1"}
              strokeWidth={isSelected ? 2 : 1}
            />
            <text
              x={NODE_W / 2}
              y={NODE_H / 2 - 4}
              textAnchor="middle"
              dominantBaseline="middle"
              fill={textColor}
              fontSize={12}
              fontWeight={isRoot ? 600 : 500}
            >
              {truncate(n.name || n._key, 22)}
            </text>
            <text
              x={NODE_W / 2}
              y={NODE_H - 12}
              textAnchor="middle"
              fill={isRoot ? "rgba(255,255,255,0.85)" : "#475569"}
              fontSize={10}
            >
              {n.tier ?? "—"}
              {n.status && n.status !== "active" ? ` · ${n.status}` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-block w-3 h-3 rounded ${swatch}`} />
      {label}
    </span>
  );
}

function SpinnerOverlay() {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="h-8 w-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
    </div>
  );
}

function EmptyState({ rootName }: { rootName: string }) {
  return (
    <div className="m-10 text-center text-sm text-gray-500">
      <p className="font-medium text-gray-700 mb-1">{rootName}</p>
      <p>
        has no <span className="font-mono">owl:imports</span> edges and is not
        imported by any other ontology.
      </p>
    </div>
  );
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, Math.max(0, max - 1)) + "…";
}
