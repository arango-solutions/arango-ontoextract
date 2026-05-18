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
import {
  IMPORTED_NODE_BORDER,
  dimColorForImported,
} from "@/components/workspace/importedEntityStyle";
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

/**
 * Stream 1 H.15: classes annotated as imported via the effective-graph
 * endpoint render with a slate border + dimmed fill, regardless of the
 * active lens. Visual constants and colour math live in
 * ``importedEntityStyle.ts`` so the box-arrow canvas and the legend agree
 * on the exact same encoding.
 */
function borderColorForLens(lens: LensType, cls: OntologyClass): string {
  if (cls.is_imported) return IMPORTED_NODE_BORDER;
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

/** Edge label shown on the canvas. In the confidence lens we append a ``%`` so
 *  the lens has visible parity with class nodes (FR-7.8.6 / workspace rule §16,
 *  "edges are first-class"). When the edge has no confidence we leave the base
 *  relation label alone so the label doesn't lie ("0%" would imply we measured
 *  it). The base label falls back to a human-readable version of the edge type
 *  when the LLM didn't supply a relation label. */
function displayEdgeLabel(
  baseLabel: string,
  edgeType: string,
  edgeConfidence: number | null | undefined,
  lens: LensType,
): string {
  const base = baseLabel || edgeType.replace(/_/g, " ");
  if (lens !== "confidence") return base;
  if (edgeConfidence == null || Number.isNaN(edgeConfidence)) return base;
  const pct = Math.round(normalizeConfidence01(edgeConfidence) * 100);
  return `${base} ${pct}%`;
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

/* ── Dark-theme hover label renderer ──────────────────── */

const HOVER_BG = "#1e1e3a";
const HOVER_TEXT = "#e2e8f0";
const HOVER_SHADOW = "rgba(0,0,0,0.6)";

function drawDarkNodeHover(
  context: CanvasRenderingContext2D,
  data: { x: number; y: number; size: number; label?: string | null; color: string },
  settings: { labelSize: number; labelFont: string; labelWeight: string },
): void {
  const size = settings.labelSize;
  const font = settings.labelFont;
  const weight = settings.labelWeight;
  context.font = `${weight} ${size}px ${font}`;

  context.fillStyle = HOVER_BG;
  context.shadowOffsetX = 0;
  context.shadowOffsetY = 2;
  context.shadowBlur = 10;
  context.shadowColor = HOVER_SHADOW;

  const PADDING = 2;

  if (typeof data.label === "string") {
    const textWidth = context.measureText(data.label).width;
    const boxWidth = Math.round(textWidth + 5);
    const boxHeight = Math.round(size + 2 * PADDING);
    const radius = Math.max(data.size, size / 2) + PADDING;
    const angleRadian = Math.asin(boxHeight / 2 / radius);
    const xDeltaCoord = Math.sqrt(
      Math.abs(Math.pow(radius, 2) - Math.pow(boxHeight / 2, 2)),
    );

    context.beginPath();
    context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
    context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2);
    context.arc(data.x, data.y, radius, angleRadian, -angleRadian);
    context.closePath();
    context.fill();
  } else {
    context.beginPath();
    context.arc(data.x, data.y, data.size + PADDING, 0, Math.PI * 2);
    context.closePath();
    context.fill();
  }

  context.shadowOffsetX = 0;
  context.shadowOffsetY = 0;
  context.shadowBlur = 0;

  if (typeof data.label === "string") {
    context.fillStyle = HOVER_TEXT;
    context.font = `${weight} ${size}px ${font}`;
    context.fillText(data.label, data.x + data.size + 3, data.y + size / 3);
  }
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
  /** When set, only edges in this set are visible (e.g. confidence-threshold
   *  filtering by ``ConfidenceThresholdSlider``). Combines additively with
   *  ``visibleNodeKeys``: an edge is visible iff both endpoints pass the node
   *  filter **and** its own ``_key`` is in this set. ``null`` disables this
   *  axis (no edge-level filter — every edge whose endpoints are visible is
   *  drawn). */
  visibleEdgeKeys?: Set<string> | null;
  /** Externally-driven node selection (e.g. sidebar click). Highlighted with a ring. */
  selectedNodeKey?: string | null;
  /** Externally-driven edge selection (e.g. sidebar click). */
  selectedEdgeKey?: string | null;
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
      borderColor: cls.is_imported ? IMPORTED_NODE_BORDER : NEUTRAL_NODE_BORDER,
      type: "bordered",
      x: pos.x,
      y: pos.y,
      confidence: cls.confidence,
      status: cls.status,
      uri: cls.uri,
      description: cls.description,
      // Effective-graph annotation fields (Stream 1 H.12 / H.15). The
      // lens painter reads ``isImported`` to dim the fill and pin the
      // border to the imported colour, regardless of which lens is
      // active; ``sourceOntologyId`` / ``sourceOntologyName`` are
      // forwarded to the right-click handler so the "Open Source
      // Ontology" menu item knows where to deep-link.
      isImported: cls.is_imported === true,
      sourceOntologyId: cls.source_ontology_id ?? null,
      sourceOntologyName: cls.source_ontology_name ?? null,
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
        // ``baseLabel`` is the lens-independent label; ``label`` is what's
        // currently shown (rewritten by ``paintLensOnGraph`` per active lens).
        baseLabel: label,
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

    const baseEdgeColor = EDGE_COLORS[edgeType] ?? "#94a3b8";
    graph.addEdgeWithKey(edge._key, source, target, {
      label: displayLabel,
      baseLabel: displayLabel,
      color: edge.is_imported ? dimColorForImported(baseEdgeColor) : baseEdgeColor,
      size: edgeType === "subclass_of" ? 2.5 : 2,
      type: "curvedArrow",
      edgeKey: edge._key,
      edgeType,
      isImported: edge.is_imported === true,
      sourceOntologyId: edge.source_ontology_id ?? null,
      sourceOntologyName: edge.source_ontology_name ?? null,
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
    // Imported entities (Stream 1 H.15): dim the lens colour towards
    // slate so the lens identity stays legible while the "not owned by
    // this ontology" signal dominates. Border is also pinned to the
    // imported colour regardless of curation lens. The painter is the
    // single place we ever touch ``color`` / ``borderColor`` after the
    // initial build, so doing the override here covers every lens
    // change without bespoke per-lens branches.
    const rawColor = lensNodeColor(cls, lens, visibleNodeKeys, ontologyTier);
    g.setNodeAttribute(
      node,
      "color",
      cls.is_imported ? dimColorForImported(rawColor) : rawColor,
    );
    g.setNodeAttribute(node, "borderColor", borderColorForLens(lens, cls));
    g.setNodeAttribute(node, "status", cls.status);
  });

  g.forEachEdge((eid) => {
    const attrs = g.getEdgeAttributes(eid);
    const ek = attrs.edgeKey as string | undefined;
    const et = attrs.edgeType as string | undefined;
    if (!ek || !et) return;
    // ``baseLabel`` is whatever was written into the topology graph at build
    // time — the LLM-supplied relation label or the synthetic-edge fallback.
    // We need it for ``displayEdgeLabel`` so the confidence-lens append is
    // consistent with the non-confidence lens.
    const baseLabel = (attrs.baseLabel as string | undefined) ?? String(attrs.label ?? "");
    const domainEdge = edges.find((ed) => ed._key === ek);
    if (!domainEdge) {
      const synEdge: OntologyEdge = {
        _key: ek,
        _from: "",
        _to: "",
        type: "rdfs_range_class",
        label: baseLabel,
      };
      const ev = lensEdgeVisual(synEdge, et, lens);
      g.setEdgeAttribute(eid, "color", ev.color);
      g.setEdgeAttribute(eid, "size", ev.size);
      g.setEdgeAttribute(eid, "label", displayEdgeLabel(baseLabel, et, null, lens));
      return;
    }
    const ev = lensEdgeVisual(domainEdge, et, lens);
    g.setEdgeAttribute(
      eid,
      "color",
      domainEdge.is_imported ? dimColorForImported(ev.color) : ev.color,
    );
    g.setEdgeAttribute(eid, "size", ev.size);
    g.setEdgeAttribute(
      eid,
      "label",
      displayEdgeLabel(baseLabel, et, domainEdge.confidence ?? null, lens),
    );
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
  /** Animate the camera to center on a specific node and highlight it. */
  focusNode: (nodeKey: string) => void;
  /** Animate the camera to center on a specific edge (midpoint of source+target). */
  focusEdge: (edgeKey: string) => void;
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
  visibleEdgeKeys,
  selectedNodeKey,
  selectedEdgeKey,
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
      defaultDrawNodeHover: drawDarkNodeHover,
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
        // Effective-graph annotation (Stream 1 H.12 / H.15). The class
        // context menu builder reads ``is_imported`` to switch to the
        // read-only + "Open Source Ontology" inventory; the source
        // fields drive the deep-link target.
        is_imported: attrs.isImported === true,
        source_ontology_id: attrs.sourceOntologyId ?? null,
        source_ontology_name: attrs.sourceOntologyName ?? null,
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
        is_imported: attrs.isImported === true,
        source_ontology_id: attrs.sourceOntologyId ?? null,
        source_ontology_name: attrs.sourceOntologyName ?? null,
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
    const hasVisFilter = !!visibleNodeKeys;
    const hasEdgeVisFilter = !!visibleEdgeKeys;
    const hasNodeSel = !!selectedNodeKey;
    const hasEdgeSel = !!selectedEdgeKey;
    const needsReducer =
      hasVisFilter || hasEdgeVisFilter || hasNodeSel || hasEdgeSel;

    if (!needsReducer) {
      s.setSetting("nodeReducer", null);
      s.setSetting("edgeReducer", null);
    } else {
      s.setSetting("nodeReducer", (_node: string, data: Record<string, unknown>) => {
        let d = data;
        if (hasVisFilter && !visibleNodeKeys!.has(_node)) {
          return { ...d, hidden: true };
        }
        if (hasNodeSel && _node === selectedNodeKey) {
          d = { ...d, highlighted: true, zIndex: 10 };
        }
        return d;
      });
      s.setSetting("edgeReducer", (edge: string, data: Record<string, unknown>) => {
        const g = graphRef.current;
        if (!g) return data;
        if (hasVisFilter) {
          const src = g.source(edge);
          const tgt = g.target(edge);
          if (!visibleNodeKeys!.has(src) || !visibleNodeKeys!.has(tgt)) {
            return { ...data, hidden: true };
          }
        }
        if (hasEdgeVisFilter) {
          const attrs = g.getEdgeAttributes(edge);
          // ``edgeKey`` is the domain key (e.g. ``150170542``); the graphology
          // ``edge`` may differ for synthetic edges (``syn-…`` prefix). The
          // filter is keyed by the domain key the slider observed.
          const ek = (attrs.edgeKey ?? edge) as string;
          if (!visibleEdgeKeys!.has(ek)) {
            return { ...data, hidden: true };
          }
        }
        if (hasEdgeSel) {
          const attrs = g.getEdgeAttributes(edge);
          if ((attrs.edgeKey ?? edge) === selectedEdgeKey) {
            return { ...data, size: (data.size as number ?? 2) + 2, color: "#818cf8", zIndex: 10 };
          }
        }
        return data;
      });
    }
    s.refresh();
  }, [visibleNodeKeys, visibleEdgeKeys, selectedNodeKey, selectedEdgeKey]);

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

  const focusNode = useCallback((nodeKey: string) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s || !g.hasNode(nodeKey)) return;

    const nodeAttrs = g.getNodeAttributes(nodeKey);

    // Compute bounding box of all visible nodes in raw graph coordinates
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    g.forEachNode((_n, a) => {
      if (a.hidden) return;
      const ax = a.x as number;
      const ay = a.y as number;
      if (ax < minX) minX = ax;
      if (ax > maxX) maxX = ax;
      if (ay < minY) minY = ay;
      if (ay > maxY) maxY = ay;
    });
    if (!isFinite(minX)) return;

    // Sigma with autoRescale normalizes the bounding box to [0, 1] camera space.
    // Camera {x: 0.5, y: 0.5, ratio: 1} shows the full graph centered.
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const x = (nodeAttrs.x - minX) / rangeX;
    const y = (nodeAttrs.y - minY) / rangeY;

    if (!isFinite(x) || !isFinite(y)) return;

    s.getCamera().animate(
      { x, y, ratio: 0.35, angle: 0 },
      { duration: 300 },
    );
  }, []);

  const focusEdge = useCallback((edgeKey: string) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s) return;

    // Find the graphology edge whose edgeKey attribute matches
    let graphEdgeId: string | null = null;
    g.forEachEdge((eid, attrs) => {
      if (attrs.edgeKey === edgeKey || eid === edgeKey) {
        graphEdgeId = eid;
      }
    });
    if (!graphEdgeId) return;

    const srcKey = g.source(graphEdgeId);
    const tgtKey = g.target(graphEdgeId);
    const srcAttrs = g.getNodeAttributes(srcKey);
    const tgtAttrs = g.getNodeAttributes(tgtKey);

    // Center on the midpoint of the two endpoint nodes
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    g.forEachNode((_n, a) => {
      if (a.hidden) return;
      const ax = a.x as number;
      const ay = a.y as number;
      if (ax < minX) minX = ax;
      if (ax > maxX) maxX = ax;
      if (ay < minY) minY = ay;
      if (ay > maxY) maxY = ay;
    });
    if (!isFinite(minX)) return;

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const midGraphX = (srcAttrs.x + tgtAttrs.x) / 2;
    const midGraphY = (srcAttrs.y + tgtAttrs.y) / 2;
    const x = (midGraphX - minX) / rangeX;
    const y = (midGraphY - minY) / rangeY;

    if (!isFinite(x) || !isFinite(y)) return;

    s.getCamera().animate(
      { x, y, ratio: 0.35, angle: 0 },
      { duration: 300 },
    );
  }, []);

  useEffect(() => {
    if (!onViewportApi) return;
    const api: SigmaViewportApi = {
      fitAll,
      centerView,
      relayout: handleRelayout,
      setEdgeStyle,
      focusNode,
      focusEdge,
    };
    onViewportApi(api);
    return () => {
      onViewportApi(null);
    };
  }, [onViewportApi, fitAll, centerView, handleRelayout, setEdgeStyle, focusNode, focusEdge]);

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
