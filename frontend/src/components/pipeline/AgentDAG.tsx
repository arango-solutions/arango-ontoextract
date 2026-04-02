"use client";

import { useMemo, useCallback } from "react";
import ReactFlow, {
  type Node,
  type Edge,
  type NodeProps,
  Position,
  Handle,
  Background,
  BackgroundVariant,
} from "reactflow";
import "reactflow/dist/style.css";
import type { StepStatus, StepStatusValue } from "@/types/pipeline";
import { PIPELINE_STEPS, STEP_LABELS, type PipelineStep } from "@/types/pipeline";

interface AgentDAGProps {
  steps: Map<string, StepStatus>;
}

const STATUS_COLORS: Record<StepStatusValue, string> = {
  pending: "border-gray-300 bg-gray-50",
  running: "border-blue-400 bg-blue-50",
  completed: "border-green-400 bg-green-50",
  failed: "border-red-400 bg-red-50",
  paused: "border-yellow-400 bg-yellow-50",
};

const STATUS_ICONS: Record<StepStatusValue, string> = {
  pending: "\u25CB",
  running: "\u25B6",
  completed: "\u2713",
  failed: "\u2717",
  paused: "\u23F8",
};

function parseTs(value?: string | number): number {
  if (value == null) return 0;
  if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
  const n = Number(value);
  if (!isNaN(n) && n > 1e9 && n < 1e12) return n * 1000;
  return new Date(value).getTime();
}

function formatElapsed(startedAt?: string, completedAt?: string): string {
  if (!startedAt) return "";
  const start = parseTs(startedAt);
  const end = completedAt ? parseTs(completedAt) : Date.now();
  if (!start || isNaN(start)) return "";
  const diffMs = Math.abs(end - start);
  if (diffMs < 1000) return `${Math.round(diffMs)}ms`;
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSec = seconds % 60;
  return `${minutes}m ${remainingSec}s`;
}

interface AgentNodeData {
  label: string;
  stepStatus: StepStatus;
  stepKey: PipelineStep;
}

function AgentNode({ data }: NodeProps<AgentNodeData>) {
  const { label, stepStatus, stepKey } = data;
  const statusValue = stepStatus.status;
  const colorClass = STATUS_COLORS[statusValue];
  const icon = STATUS_ICONS[statusValue];
  const elapsed = formatElapsed(stepStatus.startedAt, stepStatus.completedAt);

  const isDimmed =
    (stepKey === "entity_resolution_agent" || stepKey === "pre_curation_filter") &&
    statusValue === "pending";

  return (
    <div
      className={`rounded-xl border-2 px-5 py-3 min-w-[200px] shadow-sm ${colorClass} ${isDimmed ? "opacity-50" : ""}`}
      data-testid={`dag-node-${stepKey}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-300 !w-2 !h-2"
      />
      <div className="flex items-center gap-2">
        <span
          className={`text-base ${statusValue === "running" ? "animate-spin" : ""}`}
          role="img"
          aria-label={statusValue}
        >
          {icon}
        </span>
        <span className="text-sm font-semibold text-gray-800">{label}</span>
      </div>
      {elapsed && (
        <div className="text-xs text-gray-500 mt-1 ml-6">{elapsed}</div>
      )}
      {stepStatus.error && (
        <div className="text-xs text-red-600 mt-1 ml-6 truncate max-w-[180px]">
          {stepStatus.error}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-300 !w-2 !h-2"
      />
    </div>
  );
}

const nodeTypes = { agentNode: AgentNode };

const NODE_W = 220;
const NODE_GAP_Y = 110;

const PIPELINE_TOPOLOGY: { id: PipelineStep; x: number; y: number }[] = [
  { id: "strategy_selector",       x: 140, y: 0 },
  { id: "extraction_agent",        x: 140, y: NODE_GAP_Y },
  { id: "consistency_checker",     x: 140, y: NODE_GAP_Y * 2 },
  { id: "quality_judge",           x: 10,  y: NODE_GAP_Y * 3 },
  { id: "entity_resolution_agent", x: 270, y: NODE_GAP_Y * 3 },
  { id: "pre_curation_filter",     x: 140, y: NODE_GAP_Y * 4 },
];

const PIPELINE_EDGES: [PipelineStep, PipelineStep][] = [
  ["strategy_selector", "extraction_agent"],
  ["extraction_agent", "consistency_checker"],
  ["consistency_checker", "quality_judge"],
  ["consistency_checker", "entity_resolution_agent"],
  ["quality_judge", "pre_curation_filter"],
  ["entity_resolution_agent", "pre_curation_filter"],
];

export default function AgentDAG({ steps }: AgentDAGProps) {
  const { nodes, edges } = useMemo(() => {
    const flowNodes: Node<AgentNodeData>[] = PIPELINE_TOPOLOGY.map((pos) => {
      const stepStatus = steps.get(pos.id) ?? { status: "pending" as const };
      return {
        id: pos.id,
        type: "agentNode",
        position: { x: pos.x, y: pos.y },
        data: {
          label: STEP_LABELS[pos.id],
          stepStatus,
          stepKey: pos.id,
        },
        draggable: false,
      };
    });

    const flowEdges: Edge[] = PIPELINE_EDGES.map(([src, tgt]) => ({
      id: `e-${src}-${tgt}`,
      source: src,
      target: tgt,
      animated:
        steps.get(src)?.status === "completed" &&
        steps.get(tgt)?.status === "running",
      style: { stroke: "#94a3b8", strokeWidth: 2 },
    }));

    return { nodes: flowNodes, edges: flowEdges };
  }, [steps]);

  const onInit = useCallback((instance: { fitView: (opts?: Record<string, unknown>) => void }) => {
    setTimeout(() => instance.fitView({ padding: 0.15 }), 50);
  }, []);

  return (
    <div className="w-full h-[580px]" data-testid="agent-dag">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={onInit}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        zoomOnDoubleClick
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      </ReactFlow>
    </div>
  );
}
