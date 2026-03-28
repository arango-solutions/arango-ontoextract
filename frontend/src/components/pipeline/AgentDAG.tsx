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

function formatElapsed(startedAt?: string, completedAt?: string): string {
  if (!startedAt) return "";
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const diffMs = end - start;
  if (diffMs < 1000) return `${diffMs}ms`;
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

const NODE_GAP_Y = 110;
const NODE_X = 100;

export default function AgentDAG({ steps }: AgentDAGProps) {
  const { nodes, edges } = useMemo(() => {
    const flowNodes: Node<AgentNodeData>[] = PIPELINE_STEPS.map((stepKey, idx) => {
      const stepStatus = steps.get(stepKey) ?? { status: "pending" as const };
      return {
        id: stepKey,
        type: "agentNode",
        position: { x: NODE_X, y: idx * NODE_GAP_Y },
        data: {
          label: STEP_LABELS[stepKey],
          stepStatus,
          stepKey,
        },
        draggable: false,
      };
    });

    const flowEdges: Edge[] = [];
    for (let i = 0; i < PIPELINE_STEPS.length - 1; i++) {
      flowEdges.push({
        id: `e-${PIPELINE_STEPS[i]}-${PIPELINE_STEPS[i + 1]}`,
        source: PIPELINE_STEPS[i],
        target: PIPELINE_STEPS[i + 1],
        animated:
          steps.get(PIPELINE_STEPS[i])?.status === "completed" &&
          steps.get(PIPELINE_STEPS[i + 1])?.status === "running",
        style: { stroke: "#94a3b8", strokeWidth: 2 },
      });
    }

    return { nodes: flowNodes, edges: flowEdges };
  }, [steps]);

  const onInit = useCallback((instance: { fitView: () => void }) => {
    instance.fitView();
  }, []);

  return (
    <div className="w-full h-full min-h-[600px]" data-testid="agent-dag">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={onInit}
        fitView
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
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
