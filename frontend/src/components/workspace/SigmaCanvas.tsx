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
import type { LensType } from "@/components/workspace/LensToolbar";

/* ── Color palettes ──────────────────────────────────── */

const EDGE_COLORS: Record<string, string> = {
  subclass_of: "#a5b4fc",
  equivalent_class: "#c4b5fd",
  has_property: "#67e8f9",
  extends_domain: "#fcd34d",
  related_to: "#93c5fd",
  rdfs_range_class: "#93c5fd",
  extracted_from: "#6ee7b7",
  imports: "#fda4af",
};

function confidenceNodeColor(confidence: number): string {
  if (confidence > 0.7) return "#22c55e";
  if (confidence >= 0.5) return "#eab308";
  return "#ef4444";
}

const STATUS_NODE_COLORS: Record<CurationStatus, string> = {
  pending: "#94a3b8",
  approved: "#22c55e",
  rejected: "#ef4444",
};

function lensNodeColor(cls: OntologyClass, lens: LensType): string {
  switch (lens) {
    case "confidence":
      return confidenceNodeColor(cls.confidence);
    case "curation":
      return STATUS_NODE_COLORS[cls.status ?? "pending"] ?? "#94a3b8";
    case "diff":
      return "#c4b5fd";
    case "source":
      return "#7dd3fc";
    case "semantic":
    default:
      return "#818cf8";
  }
}

/* ── Props ────────────────────────────────────────────── */

const NodeBorderProgram = createNodeBorderProgram({
  borders: [
    { size: { value: 0.15 }, color: { attribute: "borderColor" } },
  ],
});

export interface SigmaCanvasProps {
  classes: OntologyClass[];
  edges: OntologyEdge[];
  activeLens: LensType;
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

/* ── Build graphology Graph from domain data ─────────── */

function buildGraph(
  classes: OntologyClass[],
  edges: OntologyEdge[],
  lens: LensType,
): Graph {
  const graph = new Graph({ multi: true, type: "directed" });

  const classKeySet = new Set(classes.map((c) => c._key));

  const degreeCounts = new Map<string, number>();
  for (const cls of classes) degreeCounts.set(cls._key, 0);

  const countableEdges = edges.filter((edge) => {
    const edgeType = getEdgeType(edge);
    if (FILTERED_FROM_CLASS_GRAPH.has(edgeType)) return false;
    const fromKey = documentKey(edge._from);
    const toKey = documentKey(edge._to);
    return classKeySet.has(fromKey) && classKeySet.has(toKey) && fromKey !== toKey;
  });

  for (const edge of countableEdges) {
    const fromKey = documentKey(edge._from);
    const toKey = documentKey(edge._to);
    degreeCounts.set(fromKey, (degreeCounts.get(fromKey) ?? 0) + 1);
    degreeCounts.set(toKey, (degreeCounts.get(toKey) ?? 0) + 1);
  }

  for (const cls of classes) {
    const degree = degreeCounts.get(cls._key) ?? 0;
    const size = Math.max(12, Math.min(30, 12 + degree * 2));
    const statusBorder =
      cls.status === "approved" ? "#22c55e"
        : cls.status === "rejected" ? "#ef4444"
        : "#f59e0b";
    graph.addNode(cls._key, {
      label: cls.label,
      size,
      color: lensNodeColor(cls, lens),
      borderColor: statusBorder,
      type: "bordered",
      x: Math.random() * 100,
      y: Math.random() * 100,
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

  return graph;
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

  const graph = useMemo(
    () => buildGraph(classes, edges, activeLens),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stableClassesKey, stableEdgesKey, activeLens],
  );

  useEffect(() => {
    if (graph.order === 0) return;
    setLayoutRunning(true);
    try {
      applyLayout(graph, "force");
    } finally {
      setLayoutRunning(false);
    }
  }, [graph]);

  const onNodeSelectRef = useRef(onNodeSelect);
  onNodeSelectRef.current = onNodeSelect;
  const onEdgeSelectRef = useRef(onEdgeSelect);
  onEdgeSelectRef.current = onEdgeSelect;
  const onContextMenuRef = useRef(onContextMenu);
  onContextMenuRef.current = onContextMenu;

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

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderer.getMouseCaptor().on("mousemovebody", (event: any) => {
      if (!isDragging || !draggedNode) return;
      const pos = renderer.viewportToGraph({ x: event.x, y: event.y });
      graph.setNodeAttribute(draggedNode, "x", pos.x);
      graph.setNodeAttribute(draggedNode, "y", pos.y);
      if (typeof event.preventSigmaDefault === "function") {
        event.preventSigmaDefault();
      }
    });

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
      onContextMenuRef.current(event.original as MouseEvent, "edge", {
        _key: attrs.edgeKey ?? edge,
        edgeType: attrs.edgeType,
        label: attrs.label,
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
    if (!graphRef.current) return;
    const g = graphRef.current;
    g.forEachNode((node) => {
      const cls = classes.find((c) => c._key === node);
      if (cls) {
        g.setNodeAttribute(node, "color", lensNodeColor(cls, activeLens));
      }
    });
    sigmaRef.current?.refresh();
  }, [activeLens, classes]);

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
