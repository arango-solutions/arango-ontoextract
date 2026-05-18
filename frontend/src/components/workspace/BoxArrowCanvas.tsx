"use client";

import { useMemo, useCallback, useEffect, useRef } from "react";
import ReactFlow, {
  type Node,
  type Edge,
  type ReactFlowInstance,
  Background,
  BackgroundVariant,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import { reactFlowErrorFilter } from "@/lib/reactFlowErrorFilter";
import ClassBoxNode, { type ClassBoxNodeData, type ClassBoxProperty } from "./ClassBoxNode";
import type { OntologyClass, OntologyEdge, CurationStatus } from "@/types/curation";
import {
  FILTERED_FROM_CLASS_GRAPH,
  getEdgeType,
  documentKey,
  buildSyntheticRdfsRangeClassEdges,
} from "@/components/graph/graphCanvasEdges";
import { ONTOLOGY_EDGE_COLORS as EDGE_COLORS } from "@/components/graph/graphVisualPalette";
import {
  confidenceNodeColor,
  normalizeConfidence01,
} from "@/components/workspace/confidenceLensPalette";
import { IMPORTED_NODE_BORDER } from "@/components/workspace/importedEntityStyle";
import type { LensType } from "@/components/workspace/LensToolbar";
import type { SigmaViewportApi, LayoutType, EdgeStyleType } from "./SigmaCanvas";

/* ── Color helpers (mirrored from SigmaCanvas) ───────── */

const STATUS_NODE_COLORS: Record<CurationStatus, string> = {
  pending: "#94a3b8",
  approved: "#22c55e",
  rejected: "#ef4444",
};

const NEUTRAL_BORDER = "#475569";

const BOX_DEFAULT_HEADER = "#6366f1";

function lensHeaderColor(
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
      return BOX_DEFAULT_HEADER;
    case "source": {
      const tier = (cls.tier ?? ontologyTier ?? "")?.toString().toLowerCase();
      if (tier === "local") return "#fbbf24";
      if (tier === "domain") return "#2dd4bf";
      return "#94a3b8";
    }
    case "semantic":
    default:
      return BOX_DEFAULT_HEADER;
  }
}

function lensBorderColor(lens: LensType, cls: OntologyClass): string {
  if (lens === "curation") {
    if (cls.status === "approved") return "#22c55e";
    if (cls.status === "rejected") return "#ef4444";
    return "#f59e0b";
  }
  return NEUTRAL_BORDER;
}

function lensEdgeColor(edgeType: string, edge: OntologyEdge, lens: LensType): string {
  if (lens === "confidence" && edge.confidence != null) {
    return confidenceNodeColor(edge.confidence);
  }
  if (lens === "curation" && edge.status) {
    const cur: Record<string, string> = {
      approved: "#22c55e",
      rejected: "#ef4444",
      pending: "#f59e0b",
    };
    return cur[edge.status] ?? EDGE_COLORS[edgeType] ?? "#94a3b8";
  }
  return EDGE_COLORS[edgeType] ?? "#94a3b8";
}

/* ── Layout with dagre ───────────────────────────────── */

const NODE_WIDTH = 220;
const NODE_BASE_HEIGHT = 40;
const PROP_ROW_HEIGHT = 16;
const MAX_VISIBLE_PROPS = 12;

function estimateNodeHeight(propCount: number): number {
  const visible = Math.min(propCount, MAX_VISIBLE_PROPS);
  const overflow = propCount > MAX_VISIBLE_PROPS ? 1 : 0;
  return NODE_BASE_HEIGHT + (visible + overflow) * PROP_ROW_HEIGHT + (visible === 0 ? PROP_ROW_HEIGHT : 0);
}

function layoutNodes(
  flowNodes: Node<ClassBoxNodeData>[],
  flowEdges: Edge[],
): Node<ClassBoxNodeData>[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80, marginx: 30, marginy: 30 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const node of flowNodes) {
    const h = estimateNodeHeight(node.data.properties.length);
    g.setNode(node.id, { width: NODE_WIDTH, height: h });
  }
  for (const edge of flowEdges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return flowNodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - pos.height / 2 },
    };
  });
}

/* ── Node types (registered once) ────────────────────── */

const nodeTypes = { classBox: ClassBoxNode };

/* ── Edge type labels ────────────────────────────────── */

const EDGE_TYPE_LABELS: Record<string, string> = {
  subclass_of: "is-a",
  equivalent_class: "≡",
  related_to: "related",
  rdfs_range_class: "range",
  rdfs_domain: "domain",
  has_property: "has",
  extends_domain: "extends",
  extracted_from: "from",
  imports: "imports",
};

/* ── Component ───────────────────────────────────────── */

export interface BoxArrowCanvasProps {
  classes: OntologyClass[];
  edges: OntologyEdge[];
  activeLens: LensType;
  ontologyTier?: "domain" | "local" | null;
  onNodeSelect: (key: string) => void;
  onEdgeSelect: (key: string) => void;
  onContextMenu: (
    e: MouseEvent,
    type: "node" | "edge" | "canvas",
    data?: Record<string, unknown>,
  ) => void;
  onViewportApi?: (api: SigmaViewportApi | null) => void;
  visibleNodeKeys?: Set<string> | null;
  selectedNodeKey?: string | null;
  selectedEdgeKey?: string | null;
  /** Properties grouped by class _key */
  classProperties?: Record<string, ClassBoxProperty[]>;
}

export default function BoxArrowCanvas({
  classes,
  edges,
  activeLens,
  ontologyTier = null,
  onNodeSelect,
  onEdgeSelect,
  onContextMenu,
  onViewportApi,
  visibleNodeKeys,
  selectedNodeKey,
  selectedEdgeKey,
  classProperties = {},
}: BoxArrowCanvasProps) {
  const rfRef = useRef<ReactFlowInstance | null>(null);
  const onContextMenuRef = useRef(onContextMenu);
  onContextMenuRef.current = onContextMenu;

  const classKeySet = useMemo(() => new Set(classes.map((c) => c._key)), [classes]);

  const { flowNodes, flowEdges } = useMemo(() => {
    const nodes: Node<ClassBoxNodeData>[] = classes.map((cls) => {
      const props = classProperties[cls._key] ?? [];
      const hidden = visibleNodeKeys != null && !visibleNodeKeys.has(cls._key);

      // Imported classes (Stream 1 H.15) render with a dashed border +
      // dimmed opacity + "imported" header pill so the user can see at
      // a glance that the class is owned by another ontology and the
      // canvas's mutating actions do not apply here. The border colour
      // is pinned to ``IMPORTED_NODE_BORDER`` (a muted slate) regardless
      // of lens, matching Sigma's encoding so the two renderers agree.
      const isImported = cls.is_imported === true;
      const borderColor = isImported
        ? IMPORTED_NODE_BORDER
        : lensBorderColor(activeLens, cls);

      return {
        id: cls._key,
        type: "classBox" as const,
        position: { x: 0, y: 0 },
        data: {
          label: cls.label,
          uri: cls.uri,
          status: cls.status,
          confidence: cls.confidence,
          headerColor: lensHeaderColor(cls, activeLens, visibleNodeKeys, ontologyTier),
          borderColor,
          properties: props,
          isSelected: selectedNodeKey === cls._key,
          isImported,
          sourceOntologyName: cls.source_ontology_name ?? null,
        },
        hidden,
        style: { pointerEvents: "all" as const },
        draggable: true,
      };
    });

    const edgesOut: Edge[] = [];

    // Structural class-to-class edges
    for (const edge of edges) {
      const edgeType = getEdgeType(edge);
      if (FILTERED_FROM_CLASS_GRAPH.has(edgeType)) continue;

      const source = documentKey(edge._from);
      const target = documentKey(edge._to);
      if (!classKeySet.has(source) || !classKeySet.has(target)) continue;

      const displayLabel = edge.label || EDGE_TYPE_LABELS[edgeType] || edgeType.replace(/_/g, " ");
      const color = lensEdgeColor(edgeType, edge, activeLens);
      const isSelected = selectedEdgeKey === edge._key;
      // Imported edges (Stream 1 H.15): draw with a dashed stroke so
      // the visual treatment matches the dashed border on imported
      // class boxes, and add a subtle opacity dip via the colour mixer
      // upstream (the renderer pipes ``stroke`` straight to SVG, so we
      // either dim the colour or set ``opacity``; we lean on stroke
      // colour to keep the dasharray crisp).
      const isImported = edge.is_imported === true;

      edgesOut.push({
        id: edge._key,
        source,
        target,
        label: displayLabel,
        labelStyle: { fill: "#94a3b8", fontSize: 10, fontWeight: 500 },
        labelBgStyle: { fill: "#1a1a2e", fillOpacity: 0.85 },
        labelBgPadding: [4, 2] as [number, number],
        style: {
          stroke: isSelected ? "#818cf8" : color,
          strokeWidth: isSelected ? 3 : (edgeType === "subclass_of" ? 2.5 : 2),
          ...(isImported ? { strokeDasharray: "6 4", opacity: 0.7 } : {}),
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: isSelected ? "#818cf8" : color },
        animated: false,
        data: { edgeKey: edge._key, edgeType, isImported },
      });
    }

    // Synthetic range edges (domain class → range class via property)
    const synEdges = buildSyntheticRdfsRangeClassEdges(edges, classKeySet);
    for (const syn of synEdges) {
      const isSelected = selectedEdgeKey === syn.edgeKey;
      const color = EDGE_COLORS.rdfs_range_class ?? "#2dd4bf";
      edgesOut.push({
        id: `syn-${syn.edgeKey}`,
        source: syn.sourceClassKey,
        target: syn.targetClassKey,
        label: syn.label,
        labelStyle: { fill: "#94a3b8", fontSize: 10, fontWeight: 500 },
        labelBgStyle: { fill: "#1a1a2e", fillOpacity: 0.85 },
        labelBgPadding: [4, 2] as [number, number],
        style: {
          stroke: isSelected ? "#818cf8" : color,
          strokeWidth: isSelected ? 3 : 2,
          strokeDasharray: "6 3",
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: isSelected ? "#818cf8" : color },
        animated: false,
        data: { edgeKey: syn.edgeKey, edgeType: "rdfs_range_class" },
      });
    }

    const laid = layoutNodes(nodes, edgesOut);
    return { flowNodes: laid, flowEdges: edgesOut };
  }, [classes, edges, activeLens, ontologyTier, visibleNodeKeys, selectedNodeKey, selectedEdgeKey, classKeySet, classProperties]);

  // Viewport API
  useEffect(() => {
    if (!onViewportApi) return;

    const api: SigmaViewportApi = {
      fitAll: () => rfRef.current?.fitView({ padding: 0.15 }),
      centerView: () => rfRef.current?.fitView({ padding: 0.3 }),
      relayout: (_layout?: LayoutType) => {
        rfRef.current?.fitView({ padding: 0.15 });
      },
      setEdgeStyle: (_style: EdgeStyleType) => {
        // React Flow handles edge styling through props
      },
      focusNode: (nodeKey: string) => {
        const rf = rfRef.current;
        if (!rf) return;
        const node = rf.getNode(nodeKey);
        if (!node) return;
        const x = node.position.x + NODE_WIDTH / 2;
        const y = node.position.y + estimateNodeHeight((classProperties[nodeKey] ?? []).length) / 2;
        rf.setCenter(x, y, { zoom: 1.2, duration: 300 });
      },
      focusEdge: (edgeKey: string) => {
        const rf = rfRef.current;
        if (!rf) return;
        const edge = rf.getEdges().find((e) => e.data?.edgeKey === edgeKey || e.id === edgeKey);
        if (!edge) return;
        const srcNode = rf.getNode(edge.source);
        const tgtNode = rf.getNode(edge.target);
        if (!srcNode || !tgtNode) return;
        const mx = (srcNode.position.x + tgtNode.position.x) / 2 + NODE_WIDTH / 2;
        const my = (srcNode.position.y + tgtNode.position.y) / 2;
        rf.setCenter(mx, my, { zoom: 1.2, duration: 300 });
      },
    };
    onViewportApi(api);
    return () => onViewportApi(null);
  }, [onViewportApi, classProperties]);

  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfRef.current = instance;
    setTimeout(() => instance.fitView({ padding: 0.15 }), 60);
  }, []);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node<ClassBoxNodeData>) => {
      onNodeSelect(node.id);
    },
    [onNodeSelect],
  );

  const handleEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      const ek = (edge.data?.edgeKey ?? edge.id) as string;
      onEdgeSelect(ek);
    },
    [onEdgeSelect],
  );

  const handleNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node<ClassBoxNodeData>) => {
      event.preventDefault();
      event.stopPropagation();
      // Forward the effective-graph annotation (Stream 1 H.12 / H.15)
      // so the class context-menu builder can switch to the read-only
      // + "Open Source Ontology" inventory when the class is imported.
      const cls = classes.find((c) => c._key === node.id);
      onContextMenuRef.current(event.nativeEvent, "node", {
        _key: node.id,
        label: node.data.label,
        uri: node.data.uri,
        status: node.data.status,
        confidence: node.data.confidence,
        is_imported: node.data.isImported === true,
        source_ontology_id: cls?.source_ontology_id ?? null,
        source_ontology_name: node.data.sourceOntologyName ?? null,
      });
    },
    [classes],
  );

  const handleEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      event.preventDefault();
      event.stopPropagation();
      const ek = (edge.data?.edgeKey ?? edge.id) as string;
      const full = edges.find((ed) => ed._key === ek);
      onContextMenuRef.current(event.nativeEvent, "edge", {
        _key: ek,
        edgeType: edge.data?.edgeType,
        label: edge.label,
        is_imported: full?.is_imported === true,
        source_ontology_id: full?.source_ontology_id ?? null,
        source_ontology_name: full?.source_ontology_name ?? null,
      });
    },
    [edges],
  );

  const handlePaneContextMenu = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      onContextMenuRef.current(event.nativeEvent, "canvas", {});
    },
    [],
  );

  // Fit view on topology change
  useEffect(() => {
    if (rfRef.current && flowNodes.length > 0) {
      setTimeout(() => rfRef.current?.fitView({ padding: 0.15 }), 80);
    }
  }, [flowNodes.length]);

  if (classes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400" data-testid="box-arrow-empty">
        <p className="text-sm">No ontology data available</p>
      </div>
    );
  }

  return (
    <div
      className="w-full h-full [&_.react-flow__pane]:!cursor-default"
      data-testid="box-arrow-canvas"
    >
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onError={reactFlowErrorFilter}
        onInit={onInit}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onNodeContextMenu={handleNodeContextMenu}
        onEdgeContextMenu={handleEdgeContextMenu}
        onPaneContextMenu={handlePaneContextMenu}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        zoomOnDoubleClick
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "smoothstep" }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#334155" />
      </ReactFlow>
    </div>
  );
}
