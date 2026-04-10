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
import {
  FILTERED_FROM_CLASS_GRAPH,
  getEdgeType,
  documentKey,
  isRelationshipEdgeStyle,
  buildSyntheticRdfsRangeClassEdges,
  RDFS_RANGE_CLASS_LABEL_FALLBACK,
} from "./graphCanvasEdges";
import { ONTOLOGY_EDGE_COLORS as EDGE_COLORS } from "./graphVisualPalette";

// --- Confidence-based color helpers ---

function confidenceColor(confidence: number): string {
  if (confidence > 0.7) return "border-green-400 bg-green-50";
  if (confidence >= 0.5) return "border-yellow-400 bg-yellow-50";
  return "border-red-400 bg-red-50";
}

function confidenceDotColor(confidence: number): string {
  if (confidence > 0.7) return "bg-green-500";
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

  const nodeSize = Math.max(160, 160 + ((confidence || 0) - 0.5) * 80);

  return (
    <div
      className={`rounded-lg ${borderWeight} ${borderStyle} px-4 py-3 shadow-sm transition-all ${colorClass} ${selected ? "ring-2 ring-blue-500 ring-offset-1" : ""}`}
      style={{ minWidth: nodeSize }}
      data-testid={`graph-node-${data.classKey}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ opacity: 0, width: 0, height: 0, border: "none", background: "none" }}
        isConnectable={false}
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
      {confidence != null && !isNaN(confidence) ? (
        <div className="mt-1 flex items-center gap-1.5">
          <span className="text-xs text-gray-400">
            {(confidence * 100).toFixed(0)}%
          </span>
          <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${confidence > 0.7 ? "bg-green-500" : confidence >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="mt-1 text-[10px] text-gray-300">Imported</div>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ opacity: 0, width: 0, height: 0, border: "none", background: "none" }}
        isConnectable={false}
      />
    </div>
  );
}

const nodeTypes = { ontologyNode: OntologyNode };

// --- Edge label config ---

// rdfs_domain / has_property are filtered (property↔class); not used for stroke.
// Stroke colors shared with Sigma workspace — see graphVisualPalette.ts.

// --- Layout: dagre automatic graph layout ---

import dagre from "dagre";

const HIERARCHY_EDGE_TYPES = new Set([
  "subclass_of",
  "extends_domain",
]);

const NODE_WIDTH = 220;
const NODE_HEIGHT = 80;

function computeLayout(
  classes: OntologyClass[],
  edges: OntologyEdge[],
): Map<string, { x: number; y: number }> {
  if (classes.length === 0) {
    return new Map();
  }

  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: "TB",
    nodesep: 80,
    ranksep: 120,
    edgesep: 40,
    marginx: 40,
    marginy: 40,
  });
  g.setDefaultEdgeLabel(() => ({}));

  const classKeySet = new Set(classes.map((c) => c._key));

  for (const cls of classes) {
    g.setNode(cls._key, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  for (const edge of edges) {
    const fromKey = edge._from.split("/").pop() ?? edge._from;
    const toKey = edge._to.split("/").pop() ?? edge._to;
    if (!classKeySet.has(fromKey) || !classKeySet.has(toKey)) continue;
    if (fromKey === toKey) continue;

    const edgeType = ((edge as unknown as Record<string, unknown>).edge_type ?? edge.type) as string;
    const isHierarchy = HIERARCHY_EDGE_TYPES.has(edgeType);

    g.setEdge(
      isHierarchy ? toKey : fromKey,
      isHierarchy ? fromKey : toKey,
    );
  }

  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  for (const cls of classes) {
    const node = g.node(cls._key);
    if (node) {
      positions.set(cls._key, {
        x: node.x - NODE_WIDTH / 2,
        y: node.y - NODE_HEIGHT / 2,
      });
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
    const fe: Edge[] = [];

    const OWL_LABELS: Record<string, string> = {
      subclass_of: "rdfs:subClassOf",
      extends_domain: "aoe:extendsDomain",
      rdfs_range_class: RDFS_RANGE_CLASS_LABEL_FALLBACK,
    };

    for (const syn of buildSyntheticRdfsRangeClassEdges(edges, classKeySet)) {
      fe.push({
        id: syn.edgeKey,
        source: syn.sourceClassKey,
        target: syn.targetClassKey,
        label: syn.label || OWL_LABELS.rdfs_range_class,
        type: "default",
        markerEnd: { type: MarkerType.ArrowClosed },
        style: {
          stroke: EDGE_COLORS.rdfs_range_class ?? "#2563eb",
          strokeWidth: 2.5,
          strokeDasharray: undefined,
        },
        labelStyle: {
          fill: "#1d4ed8",
          fontSize: 12,
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: "#eff6ff",
          fillOpacity: 0.95,
        },
        labelBgPadding: [4, 2] as [number, number],
        data: { edgeKey: syn.edgeKey },
      });
    }

    for (const edge of edges) {
      const edgeType = getEdgeType(edge);
      if (FILTERED_FROM_CLASS_GRAPH.has(edgeType)) continue;
      if (edgeType === "rdfs_range_class") continue;

      const fromKey = documentKey(edge._from);
      const toKey = documentKey(edge._to);
      if (!classKeySet.has(fromKey) || !classKeySet.has(toKey)) continue;

      const isExtendsDomain = edgeType === "extends_domain";
      const isHierarchy = edgeType === "subclass_of" || edgeType === "extends_domain";
      const relStyle = isRelationshipEdgeStyle(edgeType);
      const displayLabel = edge.label || OWL_LABELS[edgeType] || edgeType;

      fe.push({
        id: edge._key,
        source: isHierarchy ? toKey : fromKey,
        target: isHierarchy ? fromKey : toKey,
        label: displayLabel,
        type: "default",
        ...(isHierarchy
          ? { markerStart: { type: MarkerType.ArrowClosed } }
          : { markerEnd: { type: MarkerType.ArrowClosed } }),
        style: {
          stroke: EDGE_COLORS[edgeType] ?? "#94a3b8",
          strokeWidth: relStyle ? 2.5 : 2,
          strokeDasharray: isExtendsDomain ? "6 3" : undefined,
        },
        labelStyle: {
          fill: relStyle ? "#1d4ed8" : isExtendsDomain ? "#7c3aed" : "#64748b",
          fontSize: relStyle ? 12 : 11,
          fontWeight: relStyle ? 600 : 500,
        },
        labelBgStyle: {
          fill: relStyle ? "#eff6ff" : "#f8fafc",
          fillOpacity: 0.95,
        },
        labelBgPadding: [4, 2] as [number, number],
        data: { edgeKey: edge._key },
      });
    }

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
            if (conf > 0.7) return "#22c55e";
            if (conf >= 0.5) return "#eab308";
            return "#ef4444";
          }}
          className="!bg-gray-50 !border-gray-200"
        />
      </ReactFlow>
    </div>
  );
}
