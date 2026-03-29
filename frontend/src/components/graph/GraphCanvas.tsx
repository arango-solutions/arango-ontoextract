"use client";

import { useMemo, useCallback, useState } from "react";
import ReactFlow, {
  type Node,
  type Edge,
  type NodeProps,
  type OnSelectionChangeParams,
  Position,
  Handle,
  Background,
  BackgroundVariant,
  MiniMap,
  Controls,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import type {
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
  CurationStatus,
} from "@/types/curation";
import type {
  MergeCandidate,
  ExtractionClassification,
} from "@/types/entity-resolution";

// --- Confidence-based color helpers ---

function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return "border-green-400 bg-green-50";
  if (confidence >= 0.5) return "border-yellow-400 bg-yellow-50";
  return "border-red-400 bg-red-50";
}

function confidenceDotColor(confidence: number): string {
  if (confidence >= 0.8) return "bg-green-500";
  if (confidence >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

const STATUS_BORDER: Record<CurationStatus, string> = {
  pending: "border-gray-300 bg-white",
  approved: "border-green-400 bg-green-50",
  rejected: "border-red-400 bg-red-50",
};

// --- Cross-tier and classification color helpers ---

const CLASSIFICATION_COLORS: Record<ExtractionClassification, { fill: string; border: string }> = {
  EXISTING: { fill: "bg-blue-50", border: "border-blue-500" },
  EXTENSION: { fill: "bg-purple-50", border: "border-purple-500" },
  NEW: { fill: "bg-orange-50", border: "border-orange-500" },
};

type TierStyle = "domain" | "local";

function tierNodeStyle(tier: TierStyle): { borderStyle: string; fill: string; borderWeight: string } {
  if (tier === "domain") {
    return { borderStyle: "border-solid", fill: "bg-white", borderWeight: "border-2" };
  }
  return { borderStyle: "border-dashed", fill: "bg-gray-50/80", borderWeight: "border-2" };
}

function classificationMiniMapColor(classification?: ExtractionClassification): string {
  if (classification === "EXISTING") return "#3b82f6";
  if (classification === "EXTENSION") return "#a855f7";
  if (classification === "NEW") return "#f97316";
  return "#94a3b8";
}

// --- Custom Node ---

export interface OntologyNodeData {
  label: string;
  uri: string;
  rdfType: string;
  confidence: number;
  status: CurationStatus;
  classKey: string;
  description: string;
  colorMode: "confidence" | "status" | "classification" | "tier";
  classification?: ExtractionClassification;
  tier?: TierStyle;
}

function OntologyNode({ data, selected }: NodeProps<OntologyNodeData>) {
  const { label, confidence, status, rdfType, colorMode, classification, tier } = data;

  let colorClass: string;
  let borderStyle: string;
  let borderWeight = "border-2";

  if (colorMode === "classification" && classification) {
    const cc = CLASSIFICATION_COLORS[classification];
    colorClass = `${cc.border} ${cc.fill}`;
    borderStyle = "border-solid";
    borderWeight = "border-[3px]";
  } else if (colorMode === "tier" && tier) {
    const ts = tierNodeStyle(tier);
    const confColor = confidenceColor(confidence).split(" ").pop() ?? "bg-white";
    colorClass = `${ts.borderStyle === "border-dashed" ? "border-gray-400" : "border-gray-700"} ${confColor}`;
    borderStyle = ts.borderStyle;
    borderWeight = tier === "domain" ? "border-[3px]" : "border-2";
  } else if (colorMode === "status") {
    colorClass = STATUS_BORDER[status];
    borderStyle = "border-solid";
  } else {
    colorClass = confidenceColor(confidence);
    borderStyle = confidence < 0.5 ? "border-dashed" : "border-solid";
  }

  const nodeSize = Math.max(160, 160 + (confidence - 0.5) * 80);

  return (
    <div
      className={`rounded-lg ${borderWeight} ${borderStyle} px-4 py-3 shadow-sm transition-all ${colorClass} ${selected ? "ring-2 ring-blue-500 ring-offset-1" : ""}`}
      style={{ minWidth: nodeSize }}
      data-testid={`graph-node-${data.classKey}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-300 !w-2 !h-2"
      />
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`inline-block h-2 w-2 rounded-full ${confidenceDotColor(confidence)}`}
          title={`Confidence: ${(confidence * 100).toFixed(0)}%`}
        />
        <span className={`text-sm font-semibold text-gray-800 truncate ${tier === "domain" ? "font-bold" : ""}`}>
          {label}
        </span>
        {classification && (
          <span className={`text-[9px] px-1 py-0.5 rounded font-medium ${
            classification === "EXISTING" ? "bg-blue-100 text-blue-700" :
            classification === "EXTENSION" ? "bg-purple-100 text-purple-700" :
            "bg-orange-100 text-orange-700"
          }`}>
            {classification}
          </span>
        )}
      </div>
      <div className="text-xs text-gray-500 truncate">
        {rdfType}
        {tier && (
          <span className="ml-1.5 text-[10px] text-gray-400">
            ({tier === "domain" ? "Tier 1" : "Tier 2"})
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <span className="text-xs text-gray-400">
          {(confidence * 100).toFixed(0)}%
        </span>
        <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${confidence >= 0.8 ? "bg-green-500" : confidence >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-300 !w-2 !h-2"
      />
    </div>
  );
}

const nodeTypes = { ontologyNode: OntologyNode };

// --- Edge label config ---

const EDGE_COLORS: Record<string, string> = {
  subclass_of: "#6366f1",
  equivalent_class: "#8b5cf6",
  has_property: "#0891b2",
  extends_domain: "#d97706",
  related_to: "#64748b",
  extracted_from: "#059669",
  imports: "#e11d48",
};

// --- Layout: simple hierarchical using dagre-like positioning ---

const HIERARCHY_EDGE_TYPES = new Set([
  "subclass_of",
  "extends_domain",
  "related_to",
]);

function computeLayout(
  classes: OntologyClass[],
  edges: OntologyEdge[],
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const children = new Map<string, string[]>();
  const hasParent = new Set<string>();
  const allKeys = new Set(classes.map((c) => c._key));

  for (const edge of edges) {
    const edgeType = (edge as Record<string, unknown>).edge_type ?? edge.type;
    if (!HIERARCHY_EDGE_TYPES.has(edgeType as string)) continue;

    const fromKey = edge._from.split("/").pop() ?? edge._from;
    const toKey = edge._to.split("/").pop() ?? edge._to;
    if (!allKeys.has(fromKey) || !allKeys.has(toKey)) continue;

    if (!children.has(toKey)) children.set(toKey, []);
    children.get(toKey)!.push(fromKey);
    hasParent.add(fromKey);
  }

  const roots = classes.filter((c) => !hasParent.has(c._key));
  if (roots.length === 0 && classes.length > 0) {
    roots.push(classes[0]);
  }

  const COL_WIDTH = 280;
  const ROW_HEIGHT = 140;

  function placeSubtree(
    key: string,
    depth: number,
    startX: number,
    visited: Set<string>,
  ): number {
    if (visited.has(key) || !allKeys.has(key)) return startX;
    visited.add(key);

    const kids = (children.get(key) ?? []).filter((k) => !visited.has(k) && allKeys.has(k));

    if (kids.length === 0) {
      positions.set(key, { x: startX, y: depth * ROW_HEIGHT });
      return startX + COL_WIDTH;
    }

    let nextX = startX;
    for (const kid of kids) {
      nextX = placeSubtree(kid, depth + 1, nextX, visited);
    }

    const childPositions = kids
      .map((k) => positions.get(k))
      .filter((p): p is { x: number; y: number } => p != null);
    const avgX =
      childPositions.length > 0
        ? childPositions.reduce((s, p) => s + p.x, 0) / childPositions.length
        : startX;

    positions.set(key, { x: avgX, y: depth * ROW_HEIGHT });
    return nextX;
  }

  const visited = new Set<string>();
  let nextX = 0;
  for (const root of roots) {
    nextX = placeSubtree(root._key, 0, nextX, visited);
    nextX += COL_WIDTH / 2;
  }

  for (const cls of classes) {
    if (!positions.has(cls._key)) {
      positions.set(cls._key, { x: nextX, y: 0 });
      nextX += COL_WIDTH;
    }
  }

  return positions;
}

// --- Props ---

export interface GraphCanvasProps {
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
  selectedNodes?: string[];
  onNodeSelect?: (classKey: string) => void;
  onEdgeSelect?: (edgeKey: string) => void;
  onSelectionChange?: (selectedKeys: string[]) => void;
  colorMode?: "confidence" | "status" | "classification" | "tier";
  className?: string;
  mergeCandidates?: MergeCandidate[];
  showMergeCandidates?: boolean;
  classificationMap?: Record<string, ExtractionClassification>;
  tierMap?: Record<string, TierStyle>;
}

export default function GraphCanvas({
  classes,
  properties,
  edges,
  selectedNodes = [],
  onNodeSelect,
  onEdgeSelect,
  onSelectionChange,
  colorMode = "confidence",
  className = "",
  mergeCandidates = [],
  showMergeCandidates = false,
  classificationMap = {},
  tierMap = {},
}: GraphCanvasProps) {
  const [internalSelected, setInternalSelected] = useState<string[]>([]);
  const effectiveSelected = selectedNodes.length > 0 ? selectedNodes : internalSelected;

  const positions = useMemo(
    () => computeLayout(classes, edges),
    [classes, edges],
  );

  const { nodes, flowEdges } = useMemo(() => {
    const flowNodes: Node<OntologyNodeData>[] = classes.map((cls) => {
      const pos = positions.get(cls._key) ?? { x: 0, y: 0 };
      return {
        id: cls._key,
        type: "ontologyNode",
        position: pos,
        selected: effectiveSelected.includes(cls._key),
        data: {
          label: cls.label,
          uri: cls.uri,
          rdfType: cls.rdf_type,
          confidence: cls.confidence,
          status: cls.status ?? "pending",
          classKey: cls._key,
          description: cls.description,
          colorMode,
          classification: classificationMap[cls._key],
          tier: tierMap[cls._key],
        },
      };
    });

    const classKeySet = new Set(classes.map((c) => c._key));
    const fe: Edge[] = edges
      .filter((edge) => {
        const fromKey = edge._from.split("/").pop() ?? edge._from;
        const toKey = edge._to.split("/").pop() ?? edge._to;
        return classKeySet.has(fromKey) && classKeySet.has(toKey);
      })
      .map((edge) => {
        const fromKey = edge._from.split("/").pop() ?? edge._from;
        const toKey = edge._to.split("/").pop() ?? edge._to;
        const edgeType = ((edge as Record<string, unknown>).edge_type ?? edge.type) as string;
        const isExtendsDomain = edgeType === "extends_domain";
        return {
          id: edge._key,
          source: fromKey,
          target: toKey,
          label: edge.label || edgeType,
          type: "default",
          markerEnd: { type: MarkerType.ArrowClosed },
          style: {
            stroke: isExtendsDomain ? "#a855f7" : (EDGE_COLORS[edgeType] ?? "#94a3b8"),
            strokeWidth: isExtendsDomain ? 2.5 : 2,
            strokeDasharray: isExtendsDomain ? "6 3" : undefined,
          },
          labelStyle: {
            fill: isExtendsDomain ? "#7c3aed" : "#64748b",
            fontSize: 11,
            fontWeight: isExtendsDomain ? 600 : 500,
          },
          labelBgStyle: {
            fill: "#f8fafc",
            fillOpacity: 0.9,
          },
          labelBgPadding: [4, 2] as [number, number],
          data: { edgeKey: edge._key },
        };
      });

    if (showMergeCandidates && mergeCandidates.length > 0) {
      for (const mc of mergeCandidates) {
        fe.push({
          id: `mc-${mc.pair_id}`,
          source: mc.entity_1.key,
          target: mc.entity_2.key,
          label: `${(mc.overall_score * 100).toFixed(0)}%`,
          type: "default",
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: {
            stroke: "#ef4444",
            strokeWidth: 2,
            strokeDasharray: "4 4",
          },
          labelStyle: {
            fill: "#dc2626",
            fontSize: 10,
            fontWeight: 700,
          },
          labelBgStyle: {
            fill: "#fef2f2",
            fillOpacity: 0.95,
          },
          labelBgPadding: [4, 2] as [number, number],
          data: { mergeCandidate: true, pairId: mc.pair_id },
        });
      }
    }

    return { nodes: flowNodes, flowEdges: fe };
  }, [classes, edges, positions, effectiveSelected, colorMode, classificationMap, tierMap, showMergeCandidates, mergeCandidates]);

  const onInit = useCallback((instance: { fitView: () => void }) => {
    instance.fitView();
  }, []);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect?.(node.id);
    },
    [onNodeSelect],
  );

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      onEdgeSelect?.(edge.id);
    },
    [onEdgeSelect],
  );

  const handleSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      const keys = params.nodes.map((n) => n.id);
      setInternalSelected(keys);
      onSelectionChange?.(keys);
    },
    [onSelectionChange],
  );

  if (classes.length === 0) {
    return (
      <div
        className={`flex items-center justify-center h-full text-gray-400 ${className}`}
        data-testid="graph-empty"
      >
        <div className="text-center">
          <p className="text-lg">No ontology data available</p>
          <p className="text-sm mt-1">
            The staging graph is empty or still loading.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`w-full h-full min-h-[500px] ${className}`}
      data-testid="graph-canvas"
    >
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onInit={onInit}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onSelectionChange={handleSelectionChange}
        fitView
        multiSelectionKeyCode="Shift"
        selectionOnDrag
        selectNodesOnDrag
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-white !border-gray-200 !shadow-sm"
        />
        <MiniMap
          nodeColor={(node) => {
            const nd = node.data as OntologyNodeData | undefined;
            if (colorMode === "classification" && nd?.classification) {
              return classificationMiniMapColor(nd.classification);
            }
            const conf = nd?.confidence ?? 0.5;
            if (conf >= 0.8) return "#22c55e";
            if (conf >= 0.5) return "#eab308";
            return "#ef4444";
          }}
          className="!bg-gray-50 !border-gray-200"
        />
      </ReactFlow>
    </div>
  );
}
