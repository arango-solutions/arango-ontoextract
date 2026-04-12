"use client";

import { useMemo, useCallback, useEffect, useRef } from "react";
import ReactFlow, {
  type Node,
  type Edge,
  type NodeProps,
  type ReactFlowInstance,
  Position,
  Handle,
  Background,
  BackgroundVariant,
} from "reactflow";
import "reactflow/dist/style.css";
import type { StepStatus, StepStatusValue } from "@/types/pipeline";
import { PIPELINE_STEPS, STEP_LABELS, type PipelineStep } from "@/types/pipeline";

export interface AgentDAGApi {
  fitView: () => void;
  centerView: () => void;
}

interface AgentDAGProps {
  steps: Map<string, StepStatus>;
  onContextMenu?: (
    e: React.MouseEvent,
    type: "step" | "pipeline_canvas",
    data?: Record<string, unknown>,
  ) => void;
  onApi?: (api: AgentDAGApi | null) => void;
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

export default function AgentDAG({ steps, onContextMenu, onApi }: AgentDAGProps) {
  const containerRef = useRef<HTMLDivElement>(null);

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

  const rfInstance = useRef<ReactFlowInstance | null>(null);

  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfInstance.current = instance;
    setTimeout(() => instance.fitView({ padding: 0.15 }), 50);
    onApi?.({
      fitView: () => instance.fitView({ padding: 0.15 }),
      centerView: () => instance.fitView({ padding: 0.3 }),
    });
  }, [onApi]);

  // Native capture-phase contextmenu listener that fires before ReactFlow.
  // Walks the DOM from the click target to find a dag-node data-testid,
  // and dispatches the correct "step" or "pipeline_canvas" type.
  const onContextMenuRef = useRef(onContextMenu);
  onContextMenuRef.current = onContextMenu;
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function handler(e: MouseEvent) {
      e.preventDefault();
      e.stopPropagation();

      // pointer-events:none on ReactFlow node wrappers means e.target is
      // always the pane, never the node content. Use elementsFromPoint to
      // find ALL elements at the cursor including those behind pointer-events:none.
      let stepKey: string | null = null;
      const hits = document.elementsFromPoint(e.clientX, e.clientY);
      for (const hit of hits) {
        const testId = hit.getAttribute("data-testid");
        if (testId?.startsWith("dag-node-")) {
          stepKey = testId.replace("dag-node-", "");
          break;
        }
      }

      const syntheticEvent = { clientX: e.clientX, clientY: e.clientY } as unknown as React.MouseEvent;
      if (stepKey) {
        const st = stepsRef.current.get(stepKey) ?? { status: "pending" as const };
        onContextMenuRef.current?.(syntheticEvent, "step", {
          stepKey,
          label: STEP_LABELS[stepKey as PipelineStep] ?? stepKey,
          ...st,
        });
      } else {
        onContextMenuRef.current?.(syntheticEvent, "pipeline_canvas", {});
      }
    }

    el.addEventListener("contextmenu", handler, true);
    return () => el.removeEventListener("contextmenu", handler, true);
  }, []);

  useEffect(() => {
    if (rfInstance.current) {
      setTimeout(() => rfInstance.current?.fitView({ padding: 0.15 }), 100);
    }
  }, [nodes]);

  return (
    <div ref={containerRef} className="w-full h-[580px] [&_.react-flow__pane]:!cursor-default [&_.react-flow__node]:!cursor-default" data-testid="agent-dag">
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
