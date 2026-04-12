"use client";

import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import {
  EdgeArrowProgram,
  EdgeRectangleProgram,
  NodeCircleProgram,
} from "sigma/rendering";
import {
  EdgeCurvedArrowProgram,
  indexParallelEdgesIndex,
} from "@sigma/edge-curve";
import { createNodeBorderProgram } from "@sigma/node-border";
import forceAtlas2 from "graphology-layout-forceatlas2";
import noverlap from "graphology-layout-noverlap";
import { circular } from "graphology-layout";
import pagerank from "graphology-metrics/centrality/pagerank";
import type {
  OntologyClass,
  OntologyEdge,
  CurationStatus,
} from "@/types/curation";
import {
  FILTERED_FROM_CLASS_GRAPH,
  getEdgeType,
  documentKey,
  buildSyntheticRdfsRangeClassEdges,
  RDFS_RANGE_CLASS_LABEL_FALLBACK,
} from "@/components/graph/graphCanvasEdges";
import { ONTOLOGY_EDGE_COLORS as EDGE_COLORS } from "@/components/graph/graphVisualPalette";
import {
  confidenceNodeColor,
  normalizeConfidence01,
} from "@/components/workspace/confidenceLensPalette";
import type { LensType } from "@/components/workspace/LensToolbar";

/* ── Color palettes ──────────────────────────────────── */

const STATUS_NODE_COLORS: Record<CurationStatus, string> = {
  pending: "#94a3b8",
  approved: "#22c55e",
  rejected: "#ef4444",
};

/** Curation ring colors — only used when the active lens is "curation". */
function statusBorderForClass(cls: OntologyClass): string {
  if (cls.status === "approved") return "#22c55e";
  if (cls.status === "rejected") return "#ef4444";
  return "#f59e0b";
}

/** Neutral outline so semantic/confidence/diff/source lenses are not dominated by curation. */
const NEUTRAL_NODE_BORDER = "#475569";

function borderColorForLens(lens: LensType, cls: OntologyClass): string {
  if (lens === "curation") return statusBorderForClass(cls);
  return NEUTRAL_NODE_BORDER;
}

/** Deterministic layout seed so lens switches do not reshuffle the graph. */
function stableNodePosition(nodeKey: string): { x: number; y: number } {
  let h = 0;
  for (let i = 0; i < nodeKey.length; i++) {
    h = (Math.imul(31, h) + nodeKey.charCodeAt(i)) | 0;
  }
  const u = (h % 1000) / 1000;
  const v = ((h >>> 8) % 1000) / 1000;
  return { x: u * 200 - 100, y: v * 200 - 100 };
}

/** Semantic lens: varied hues by URI hash + bright OWL-type hints (dark canvas). */
function semanticNodeColor(cls: OntologyClass): string {
  const rt = (cls.rdf_type || "").toLowerCase();
  if (rt.includes("objectproperty")) return "#e879f9";
  if (rt.includes("datatype")) return "#7dd3fc";
  if (rt.includes("restriction")) return "#fdba74";
  let h = 0;
  const s = cls.uri || cls._key;
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  }
  const hue = 18 + (Math.abs(h) % 312);
  return `hsl(${hue}, 82%, 70%)`;
}

function effectiveTier(
  cls: OntologyClass,
  ontologyTier: "domain" | "local" | null | undefined,
): string | undefined {
  return cls.tier ?? ontologyTier ?? undefined;
}

function lensNodeColor(
  cls: OntologyClass,
  lens: LensType,
  visibleNodeKeys: Set<string> | null | undefined,
  ontologyTier: "domain" | "local" | null | undefined,
): string {
  switch (lens) {
    case "confidence":
      return confidenceNodeColor(cls.confidence ?? 0.5);
    case "curation":
      return STATUS_NODE_COLORS[cls.status ?? "pending"] ?? "#94a3b8";
    case "diff":
      if (visibleNodeKeys != null && visibleNodeKeys.size > 0) {
        return visibleNodeKeys.has(cls._key) ? "#34d399" : "#475569";
      }
      return semanticNodeColor(cls);
    case "source": {
      const tier = effectiveTier(cls, ontologyTier)?.toLowerCase();
      if (tier === "local") return "#fbbf24";
      if (tier === "domain") return "#2dd4bf";
      return "#94a3b8";
    }
    case "semantic":
    default:
      return semanticNodeColor(cls);
  }
}

function lensNodeSize(
  baseSize: number,
  cls: OntologyClass,
  lens: LensType,
): number {
  if (lens !== "confidence") return baseSize;
  const c = normalizeConfidence01(cls.confidence ?? 0.5);
  const scale = 0.72 + 0.56 * Math.min(1, Math.max(0, c));
  return Math.max(10, Math.min(36, baseSize * scale));
}

function displayNodeLabel(cls: OntologyClass, lens: LensType): string {
  if (lens !== "confidence") return cls.label;
  const pct = Math.round(normalizeConfidence01(cls.confidence ?? 0) * 100);
  return `${cls.label} ${pct}%`;
}

function lensEdgeVisual(
  edge: OntologyEdge,
  edgeType: string,
  lens: LensType,
): { color: string; size: number } {
  const fallbackColor = EDGE_COLORS[edgeType] ?? "#94a3b8";
  const baseSize = edgeType === "subclass_of" ? 2.5 : 2;

  if (lens === "confidence") {
    const c = edge.confidence;
    if (c == null || Number.isNaN(c)) {
      return {
        color: fallbackColor,
        size: Math.max(1, baseSize * 0.85),
      };
    }
    return {
      color: confidenceNodeColor(c),
      size: Math.max(1.2, Math.min(5, 1.1 + c * 3.5)),
    };
  }

  if (lens === "curation" && edge.status) {
    const cur: Record<string, string> = {
      approved: "#22c55e",
      rejected: "#ef4444",
      pending: "#f59e0b",
    };
    return {
      color: cur[edge.status] ?? fallbackColor,
      size: baseSize * 1.15,
    };
  }

  return { color: fallbackColor, size: baseSize };
}

/* ── Props ────────────────────────────────────────────── */

/** Outer ring = `borderColor` (e.g. curation); inner fill = `color` (lens / semantic).
 * A single-border config omits the fill pass and Sigma's shader divides by zero fill count,
 * so `color` never appears — confidence/semantic fills looked grey. */
const NodeBorderProgram = createNodeBorderProgram({
  borders: [
    { size: { value: 0.15 }, color: { attribute: "borderColor" } },
    { size: { fill: true }, color: { attribute: "color" } },
  ],
});

export interface SigmaCanvasProps {
  classes: OntologyClass[];
  edges: OntologyEdge[];
  activeLens: LensType;
  /** Registry tier for the open ontology — classes often omit ``tier`` on each vertex */
  ontologyTier?: "domain" | "local" | null;
  onNodeSelect: (key: string) => void;
  onEdgeSelect: (key: string) => void;
  onContextMenu: (
    e: MouseEvent,
    type: "node" | "edge" | "canvas",
    data?: Record<string, unknown>,
  ) => void;
  /** Called when Sigma is ready or torn down (null on unmount). */
  onViewportApi?: (api: SigmaViewportApi | null) => void;
  /** When set, only nodes in this set are visible (VCR timeline filtering). */
  visibleNodeKeys?: Set<string> | null;
}

/* ── Topology graph (lens-independent positions & structure) ── */

function buildTopologyGraph(classes: OntologyClass[], edges: OntologyEdge[]): Graph {
  const graph = new Graph({ multi: true, type: "directed" });

  const classKeySet = new Set(classes.map((c) => c._key));

  for (const cls of classes) {
    const pos = stableNodePosition(cls._key);
    graph.addNode(cls._key, {
      label: cls.label,
      size: 18,
      baseSize: 18,
      color: "#64748b",
      borderColor: NEUTRAL_NODE_BORDER,
      type: "bordered",
      x: pos.x,
      y: pos.y,
      confidence: cls.confidence,
      status: cls.status,
      uri: cls.uri,
      description: cls.description,
    });
  }

  const syntheticEdges = buildSyntheticRdfsRangeClassEdges(edges, classKeySet);
  for (const syn of syntheticEdges) {
    const label = syn.label || RDFS_RANGE_CLASS_LABEL_FALLBACK;
    graph.addEdgeWithKey(
      `syn-${syn.edgeKey}`,
      syn.sourceClassKey,
      syn.targetClassKey,
      {
        label,
        color: EDGE_COLORS.rdfs_range_class,
        size: 2,
        type: "curvedArrow",
        edgeKey: syn.edgeKey,
        edgeType: "rdfs_range_class",
      },
    );
  }

  for (const edge of edges) {
    const edgeType = getEdgeType(edge);
    if (FILTERED_FROM_CLASS_GRAPH.has(edgeType)) continue;
    if (edgeType === "rdfs_range_class") continue;

    const fromKey = documentKey(edge._from);
    const toKey = documentKey(edge._to);
    if (!classKeySet.has(fromKey) || !classKeySet.has(toKey)) continue;
    if (fromKey === toKey) continue;

    const isHierarchy = edgeType === "subclass_of" || edgeType === "extends_domain";
    const source = isHierarchy ? fromKey : fromKey;
    const target = isHierarchy ? toKey : toKey;

    const displayLabel = edge.label || edgeType.replace(/_/g, " ");

    graph.addEdgeWithKey(edge._key, source, target, {
      label: displayLabel,
      color: EDGE_COLORS[edgeType] ?? "#94a3b8",
      size: edgeType === "subclass_of" ? 2.5 : 2,
      type: "curvedArrow",
      edgeKey: edge._key,
      edgeType,
    });
  }

  if (graph.order > 0) {
    try {
      pagerank.assign(graph);
    } catch {
      // Very small / degenerate graphs — fall back to degree below
    }
    let minP = Infinity;
    let maxP = -Infinity;
    graph.forEachNode((node) => {
      const p = graph.getNodeAttribute(node, "pagerank") as number | undefined;
      if (typeof p === "number" && !Number.isNaN(p)) {
        minP = Math.min(minP, p);
        maxP = Math.max(maxP, p);
      }
    });
    if (Number.isFinite(minP) && maxP > minP) {
      graph.forEachNode((node) => {
        const p = graph.getNodeAttribute(node, "pagerank") as number;
        const t = (p - minP) / (maxP - minP);
        const baseSize = 12 + t * 18;
        const clamped = Math.max(12, Math.min(30, baseSize));
        graph.setNodeAttribute(node, "baseSize", clamped);
        graph.setNodeAttribute(node, "size", clamped);
      });
    } else {
      graph.forEachNode((node) => {
        const d = graph.degree(node);
        const baseSize = Math.max(12, Math.min(30, 12 + d * 2));
        graph.setNodeAttribute(node, "baseSize", baseSize);
        graph.setNodeAttribute(node, "size", baseSize);
      });
    }
  }

  return graph;
}

function paintLensOnGraph(
  g: Graph,
  classes: OntologyClass[],
  edges: OntologyEdge[],
  lens: LensType,
  visibleNodeKeys: Set<string> | null | undefined,
  ontologyTier: "domain" | "local" | null | undefined,
): void {
  g.forEachNode((node) => {
    const cls = classes.find((c) => c._key === node);
    if (!cls) return;
    const stored = g.getNodeAttribute(node, "baseSize") as number | undefined;
    const baseSize =
      typeof stored === "number" && !Number.isNaN(stored)
        ? stored
        : Math.max(12, Math.min(30, 12 + g.degree(node) * 2));
    const sized = lensNodeSize(baseSize, cls, lens);
    g.setNodeAttribute(node, "size", sized);
    g.setNodeAttribute(node, "label", displayNodeLabel(cls, lens));
    g.setNodeAttribute(
      node,
      "color",
      lensNodeColor(cls, lens, visibleNodeKeys, ontologyTier),
    );
    g.setNodeAttribute(node, "borderColor", borderColorForLens(lens, cls));
    g.setNodeAttribute(node, "status", cls.status);
  });

  g.forEachEdge((eid) => {
    const attrs = g.getEdgeAttributes(eid);
    const ek = attrs.edgeKey as string | undefined;
    const et = attrs.edgeType as string | undefined;
    if (!ek || !et) return;
    const domainEdge = edges.find((ed) => ed._key === ek);
    if (!domainEdge) {
      const synEdge: OntologyEdge = {
        _key: ek,
        _from: "",
        _to: "",
        type: "rdfs_range_class",
        label: String(attrs.label ?? ""),
      };
      const ev = lensEdgeVisual(synEdge, et, lens);
      g.setEdgeAttribute(eid, "color", ev.color);
      g.setEdgeAttribute(eid, "size", ev.size);
      return;
    }
    const ev = lensEdgeVisual(domainEdge, et, lens);
    g.setEdgeAttribute(eid, "color", ev.color);
    g.setEdgeAttribute(eid, "size", ev.size);
  });
}

/**
 * Reset camera to show the full graph.
 *
 * Sigma v3 with autoRescale (default) normalizes node positions to fit the
 * viewport, so the default camera state {x:0.5, y:0.5, ratio:1} already
 * shows everything. We just need to reset to that default.
 */
function fitCameraToGraph(sigma: Sigma): void {
  sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });
  sigma.refresh();
}

function centerCameraOnGraph(sigma: Sigma): void {
  sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });
  sigma.refresh();
}

export type LayoutType = "force" | "circular" | "grid" | "random";
export type EdgeStyleType = "curved" | "straight";

function applyLayout(graph: Graph, layout: LayoutType): void {
  switch (layout) {
    case "circular":
      circular.assign(graph, { scale: 100 });
      break;
    case "grid": {
      const nodes = graph.nodes();
      const cols = Math.ceil(Math.sqrt(nodes.length));
      const spacing = 10;
      nodes.forEach((node, i) => {
        graph.setNodeAttribute(node, "x", (i % cols) * spacing);
        graph.setNodeAttribute(node, "y", Math.floor(i / cols) * spacing);
      });
      break;
    }
    case "random":
      graph.forEachNode((node) => {
        graph.setNodeAttribute(node, "x", Math.random() * 200 - 100);
        graph.setNodeAttribute(node, "y", Math.random() * 200 - 100);
      });
      break;
    case "force":
    default:
      forceAtlas2.assign(graph, {
        iterations: 150,
        settings: {
          gravity: 5,
          scalingRatio: 20,
          strongGravityMode: true,
          barnesHutOptimize: graph.order > 50,
        },
      });
      noverlap.assign(graph, { maxIterations: 50, settings: { ratio: 2 } });
      break;
  }
}

/** Imperative controls for parent (workspace context menu, shortcuts). */
export interface SigmaViewportApi {
  fitAll: () => void;
  centerView: () => void;
  relayout: (layout?: LayoutType) => void;
  setEdgeStyle: (style: EdgeStyleType) => void;
}

/* ── Component ────────────────────────────────────────── */

export default function SigmaCanvas({
  classes,
  edges,
  activeLens,
  ontologyTier = null,
  onNodeSelect,
  onEdgeSelect,
  onContextMenu,
  onViewportApi,
  visibleNodeKeys,
}: SigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [layoutRunning, setLayoutRunning] = useState(false);

  const stableClassesKey = useMemo(
    () => classes.map((c) => c._key).sort().join(","),
    [classes],
  );
  const stableEdgesKey = useMemo(
    () => edges.map((e) => e._key).sort().join(","),
    [edges],
  );

  const topologySignature = `${stableClassesKey}|${stableEdgesKey}`;
  const lastLaidOutTopologyRef = useRef<string>("");

  const graph = useMemo(
    () => buildTopologyGraph(classes, edges),
    // Rebuild only when vertex/edge keys change — class field updates repaint via paintLensOnGraph.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stableClassesKey, stableEdgesKey],
  );

  useEffect(() => {
    if (graph.order === 0) return;
    if (lastLaidOutTopologyRef.current === topologySignature) return;
    lastLaidOutTopologyRef.current = topologySignature;
    setLayoutRunning(true);
    try {
      applyLayout(graph, "force");
    } finally {
      setLayoutRunning(false);
    }
  }, [graph, topologySignature]);

  useEffect(() => {
    if (graph.order === 0) return;
    paintLensOnGraph(graph, classes, edges, activeLens, visibleNodeKeys, ontologyTier);
    sigmaRef.current?.refresh();
  }, [graph, classes, edges, activeLens, visibleNodeKeys, ontologyTier]);

  const onNodeSelectRef = useRef(onNodeSelect);
  onNodeSelectRef.current = onNodeSelect;
  const onEdgeSelectRef = useRef(onEdgeSelect);
  onEdgeSelectRef.current = onEdgeSelect;
  const onContextMenuRef = useRef(onContextMenu);
  onContextMenuRef.current = onContextMenu;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;

  useEffect(() => {
    if (!containerRef.current || graph.order === 0) return;
    graphRef.current = graph;

    indexParallelEdgesIndex(graph, {
      edgeIndexAttribute: "parallelIndex",
      edgeMaxIndexAttribute: "parallelMaxIndex",
    });

    const renderer = new Sigma(graph, containerRef.current, {
      renderLabels: true,
      renderEdgeLabels: true,
      labelRenderedSizeThreshold: 6,
      labelColor: { color: "#e2e8f0" },
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 13,
      edgeLabelColor: { color: "#94a3b8" },
      edgeLabelFont: "Inter, system-ui, sans-serif",
      edgeLabelSize: 10,
      defaultNodeType: "bordered",
      defaultEdgeType: "curvedArrow",
      stagePadding: 40,
      enableEdgeEvents: true,
      nodeProgramClasses: {
        circle: NodeCircleProgram,
        bordered: NodeBorderProgram,
      },
      edgeProgramClasses: {
        curvedArrow: EdgeCurvedArrowProgram,
        arrow: EdgeArrowProgram,
        line: EdgeRectangleProgram,
      },
    });

    sigmaRef.current = renderer;

    let killed = false;
    let retryCount = 0;
    const MAX_RETRIES = 30;

    const afterLayout = () => {
      if (killed) return;
      renderer.resize();
      const dims = renderer.getDimensions();
      if (dims.width === 0 || dims.height === 0) {
        retryCount++;
        if (retryCount < MAX_RETRIES) {
          setTimeout(afterLayout, 100);
        }
        return;
      }
      renderer.refresh();
      fitCameraToGraph(renderer);
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(afterLayout);
    });

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            if (killed) return;
            const el = containerRef.current;
            if (!el || el.offsetWidth === 0 || el.offsetHeight === 0) return;
            renderer.resize();
            renderer.refresh();
            fitCameraToGraph(renderer);
          })
        : null;
    resizeObserver?.observe(containerRef.current);

    let hoveredNode: string | null = null;
    let draggedNode: string | null = null;
    let isDragging = false;

    renderer.on("enterNode", ({ node }) => {
      if (killed) return;
      hoveredNode = node;
      renderer.setSetting("labelRenderedSizeThreshold", 0);
      graph.setNodeAttribute(node, "highlighted", true);
      renderer.refresh();
    });

    renderer.on("leaveNode", ({ node }) => {
      if (killed) return;
      hoveredNode = null;
      renderer.setSetting("labelRenderedSizeThreshold", 6);
      graph.setNodeAttribute(node, "highlighted", false);
      renderer.refresh();
    });

    renderer.on("downNode", ({ node, event }) => {
      if ("button" in event.original && event.original.button !== 0) return;
      isDragging = true;
      draggedNode = node;
      graph.setNodeAttribute(node, "highlighted", true);
      renderer.setSetting("enableCameraPanning", false);
    });

    renderer.getMouseCaptor().on(
      "mousemovebody",
      (event: { x: number; y: number; preventSigmaDefault?: () => void }) => {
        if (!isDragging || !draggedNode) return;
        const pos = renderer.viewportToGraph({ x: event.x, y: event.y });
        graph.setNodeAttribute(draggedNode, "x", pos.x);
        graph.setNodeAttribute(draggedNode, "y", pos.y);
        event.preventSigmaDefault?.();
      },
    );

    renderer.getMouseCaptor().on("mouseup", () => {
      if (draggedNode) {
        graph.setNodeAttribute(draggedNode, "highlighted", false);
      }
      isDragging = false;
      draggedNode = null;
      renderer.setSetting("enableCameraPanning", true);
    });

    renderer.on("clickNode", ({ node }) => {
      if (isDragging) return;
      onNodeSelectRef.current(node);
    });

    renderer.on("clickEdge", ({ edge }) => {
      const attrs = graph.getEdgeAttributes(edge);
      onEdgeSelectRef.current(attrs.edgeKey ?? edge);
    });

    renderer.on("rightClickNode", ({ node, event }) => {
      event.original.preventDefault();
      const attrs = graph.getNodeAttributes(node);
      onContextMenuRef.current(event.original as MouseEvent, "node", {
        _key: node,
        label: attrs.label,
        confidence: attrs.confidence,
        status: attrs.status,
        uri: attrs.uri,
      });
    });

    renderer.on("rightClickEdge", ({ edge, event }) => {
      event.original.preventDefault();
      const attrs = graph.getEdgeAttributes(edge);
      const ek = (attrs.edgeKey ?? edge) as string;
      const full = edgesRef.current.find((ed) => ed._key === ek);
      onContextMenuRef.current(event.original as MouseEvent, "edge", {
        _key: ek,
        edgeType: attrs.edgeType,
        label: attrs.label,
        status: full?.status,
      });
    });

    renderer.on("rightClickStage", ({ event }) => {
      event.original.preventDefault();
      onContextMenuRef.current(event.original as MouseEvent, "canvas");
    });

    return () => {
      killed = true;
      resizeObserver?.disconnect();
      renderer.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, [graph]);

  useEffect(() => {
    const s = sigmaRef.current;
    if (!s) return;
    if (!visibleNodeKeys) {
      s.setSetting("nodeReducer", null);
      s.setSetting("edgeReducer", null);
    } else {
      s.setSetting("nodeReducer", (_node: string, data: Record<string, unknown>) => {
        if (!visibleNodeKeys.has(_node)) {
          return { ...data, hidden: true };
        }
        return data;
      });
      s.setSetting("edgeReducer", (edge: string, data: Record<string, unknown>) => {
        const g = graphRef.current;
        if (!g) return data;
        const src = g.source(edge);
        const tgt = g.target(edge);
        if (!visibleNodeKeys.has(src) || !visibleNodeKeys.has(tgt)) {
          return { ...data, hidden: true };
        }
        return data;
      });
    }
    s.refresh();
  }, [visibleNodeKeys]);

  const handleRelayout = useCallback((layout: LayoutType = "force") => {
    if (!graphRef.current || !sigmaRef.current) return;
    setLayoutRunning(true);
    try {
      applyLayout(graphRef.current, layout);
      sigmaRef.current.resize();
      sigmaRef.current.refresh();
      fitCameraToGraph(sigmaRef.current);
    } finally {
      setLayoutRunning(false);
    }
  }, []);

  const fitAll = useCallback(() => {
    const s = sigmaRef.current;
    if (!s) return;
    s.resize();
    s.refresh();
    fitCameraToGraph(s);
  }, []);

  const centerView = useCallback(() => {
    const s = sigmaRef.current;
    if (!s) return;
    centerCameraOnGraph(s);
  }, []);

  const setEdgeStyle = useCallback((style: EdgeStyleType) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s) return;
    const edgeType = style === "curved" ? "curvedArrow" : "arrow";
    g.forEachEdge((edge) => {
      g.setEdgeAttribute(edge, "type", edgeType);
    });
    s.refresh();
  }, []);

  useEffect(() => {
    if (!onViewportApi) return;
    const api: SigmaViewportApi = {
      fitAll,
      centerView,
      relayout: handleRelayout,
      setEdgeStyle,
    };
    onViewportApi(api);
    return () => {
      onViewportApi(null);
    };
  }, [onViewportApi, fitAll, centerView, handleRelayout, setEdgeStyle]);

  if (classes.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-gray-500"
        data-testid="sigma-empty"
      >
        <div className="text-center">
          <p className="text-lg">No ontology data available</p>
          <p className="text-sm mt-1 text-gray-400">
            The staging graph is empty or still loading.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="sigma-canvas"
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#111118",
        overflow: "hidden",
      }}
    >
      {layoutRunning && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin h-10 w-10 border-3 border-indigo-400 border-t-transparent rounded-full" />
            <p className="text-sm text-gray-300">Computing layout…</p>
          </div>
        </div>
      )}
      {/* Node/edge count — subtle top-left overlay */}
      <div className="absolute bottom-2 right-2 z-20 text-[10px] text-gray-600 pointer-events-none">
        {graph.order} nodes &middot; {graph.size} edges
      </div>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          position: "relative",
        }}
      />
    </div>
  );
}
