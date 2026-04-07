"use client";

import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import {
  EdgeArrowProgram,
  EdgeRectangleProgram,
  NodeCircleProgram,
} from "sigma/rendering";
import forceAtlas2 from "graphology-layout-forceatlas2";
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
  subclass_of: "#818cf8",
  equivalent_class: "#a78bfa",
  has_property: "#22d3ee",
  extends_domain: "#fbbf24",
  related_to: "#60a5fa",
  rdfs_range_class: "#60a5fa",
  extracted_from: "#34d399",
  imports: "#fb7185",
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
      return "#a78bfa";
    case "source":
      return "#38bdf8";
    case "semantic":
    default:
      return "#6366f1";
  }
}

/* ── Props ────────────────────────────────────────────── */

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
    const size = Math.max(8, Math.min(24, 8 + degree * 2));
    graph.addNode(cls._key, {
      label: cls.label,
      size,
      color: lensNodeColor(cls, lens),
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
        type: "arrow",
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
      color: EDGE_COLORS[edgeType] ?? "#64748b",
      size: edgeType === "subclass_of" ? 2.5 : 2,
      type: "arrow",
      edgeKey: edge._key,
      edgeType,
    });
  }

  return graph;
}

/** Fit camera so the full graph bbox is visible (Sigma v3). */
function fitCameraToGraph(sigma: Sigma): void {
  const { width: vw, height: vh } = sigma.getDimensions();
  if (vw <= 0 || vh <= 0) return;

  const bbox = sigma.getBBox();
  const gw = Math.max(bbox.x[1] - bbox.x[0], 1e-6);
  const gh = Math.max(bbox.y[1] - bbox.y[0], 1e-6);
  const cx = (bbox.x[0] + bbox.x[1]) / 2;
  const cy = (bbox.y[0] + bbox.y[1]) / 2;

  const pad = sigma.getStagePadding() * 2;
  const ratio = Math.max(gw / (vw - pad), gh / (vh - pad));

  sigma.getCamera().setState({
    x: cx,
    y: cy,
    ratio: Math.max(ratio, 1e-6),
    angle: 0,
  });
  sigma.refresh();
}

/** Pan camera to graph centroid without changing zoom (current ratio preserved). */
function centerCameraOnGraph(sigma: Sigma): void {
  const bbox = sigma.getBBox();
  const cx = (bbox.x[0] + bbox.x[1]) / 2;
  const cy = (bbox.y[0] + bbox.y[1]) / 2;
  const cam = sigma.getCamera();
  const prev = cam.getState();
  cam.setState({
    x: cx,
    y: cy,
    ratio: prev.ratio,
    angle: prev.angle,
  });
  sigma.refresh();
}

/** Imperative controls for parent (workspace context menu, shortcuts). */
export interface SigmaViewportApi {
  fitAll: () => void;
  centerView: () => void;
  relayout: () => void;
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
      forceAtlas2.assign(graph, {
        iterations: 100,
        settings: {
          gravity: 1,
          scalingRatio: 10,
          barnesHutOptimize: graph.order > 50,
        },
      });
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

    const renderer = new Sigma(graph, containerRef.current, {
      renderLabels: true,
      labelRenderedSizeThreshold: 6,
      labelColor: { color: "#e2e8f0" },
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 13,
      edgeLabelColor: { color: "#94a3b8" },
      edgeLabelFont: "Inter, system-ui, sans-serif",
      edgeLabelSize: 10,
      defaultEdgeType: "arrow",
      stagePadding: 40,
      enableEdgeEvents: true,
      // sigma is marked sideEffects:false; default WebGL programs can be tree-shaken.
      nodeProgramClasses: { circle: NodeCircleProgram },
      edgeProgramClasses: {
        arrow: EdgeArrowProgram,
        line: EdgeRectangleProgram,
      },
    });

    sigmaRef.current = renderer;

    let killed = false;

    const afterLayout = () => {
      if (killed) return;
      renderer.resize();
      const dims = renderer.getDimensions();
      if (dims.width === 0 || dims.height === 0) {
        setTimeout(afterLayout, 100);
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

    renderer.on("clickNode", ({ node }) => {
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

  const handleRelayout = useCallback(() => {
    if (!graphRef.current || !sigmaRef.current) return;
    setLayoutRunning(true);
    try {
      forceAtlas2.assign(graphRef.current, {
        iterations: 100,
        settings: {
          gravity: 1,
          scalingRatio: 10,
          barnesHutOptimize: graphRef.current.order > 50,
        },
      });
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

  useEffect(() => {
    if (!onViewportApi) return;
    const api: SigmaViewportApi = {
      fitAll,
      centerView,
      relayout: handleRelayout,
    };
    onViewportApi(api);
    return () => {
      onViewportApi(null);
    };
  }, [onViewportApi, fitAll, centerView, handleRelayout]);

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
    <div className="relative w-full h-full" data-testid="sigma-canvas">
      {layoutRunning && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin h-10 w-10 border-3 border-indigo-400 border-t-transparent rounded-full" />
            <p className="text-sm text-gray-300">Computing layout…</p>
          </div>
        </div>
      )}
      <div
        ref={containerRef}
        className="absolute inset-0"
        style={{ background: "#1a1a2e", width: "100%", height: "100%" }}
      />
    </div>
  );
}
