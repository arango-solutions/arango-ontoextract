"use client";

import type { StepStatus, StepStatusValue } from "@/types/pipeline";
import { PIPELINE_STEPS, STEP_LABELS, type PipelineStep } from "@/types/pipeline";

interface RunTimelineProps {
  steps: Map<string, StepStatus>;
}

const BAR_COLORS: Record<StepStatusValue, string> = {
  pending: "#d1d5db",
  running: "#3b82f6",
  completed: "#22c55e",
  failed: "#ef4444",
  paused: "#eab308",
};

const BAR_HEIGHT = 28;
const ROW_HEIGHT = 44;
const LABEL_WIDTH = 160;
const CHART_PADDING = 16;
const MIN_BAR_WIDTH = 4;

function computeTimeRange(steps: Map<string, StepStatus>): {
  minTs: number;
  maxTs: number;
} {
  let minTs = Infinity;
  let maxTs = -Infinity;

  steps.forEach((step) => {
    if (step.startedAt) {
      const t = new Date(step.startedAt).getTime();
      if (t < minTs) minTs = t;
      if (t > maxTs) maxTs = t;
    }
    if (step.completedAt) {
      const t = new Date(step.completedAt).getTime();
      if (t > maxTs) maxTs = t;
    }
  });

  const hasActive = Array.from(steps.values()).some(
    (s) => s.status === "running",
  );
  if (hasActive) {
    const now = Date.now();
    if (now > maxTs) maxTs = now;
  }

  if (!isFinite(minTs) || !isFinite(maxTs)) {
    const now = Date.now();
    return { minTs: now, maxTs: now + 1000 };
  }

  if (maxTs <= minTs) maxTs = minTs + 1000;

  return { minTs, maxTs };
}

function formatAxisTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function RunTimeline({ steps }: RunTimelineProps) {
  const activeSteps = PIPELINE_STEPS.filter((key) => {
    const s = steps.get(key);
    return s && s.status !== "pending";
  });

  if (activeSteps.length === 0) {
    return (
      <div className="p-4 text-sm text-gray-400" data-testid="timeline-empty">
        No step timing data available yet.
      </div>
    );
  }

  const { minTs, maxTs } = computeTimeRange(steps);
  const totalDuration = maxTs - minTs;

  const svgWidth = 600;
  const chartWidth = svgWidth - LABEL_WIDTH - CHART_PADDING * 2;
  const svgHeight = PIPELINE_STEPS.length * ROW_HEIGHT + 40;

  return (
    <div className="p-4 overflow-x-auto" data-testid="run-timeline">
      <svg
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full max-w-full"
        preserveAspectRatio="xMinYMin meet"
      >
        {PIPELINE_STEPS.map((stepKey, idx) => {
          const step = steps.get(stepKey);
          const y = idx * ROW_HEIGHT + 10;

          return (
            <g key={stepKey}>
              <text
                x={LABEL_WIDTH - 8}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="end"
                className="text-xs fill-gray-600"
                style={{ fontSize: "11px" }}
              >
                {STEP_LABELS[stepKey]}
              </text>

              <line
                x1={LABEL_WIDTH}
                y1={y + BAR_HEIGHT / 2}
                x2={svgWidth - CHART_PADDING}
                y2={y + BAR_HEIGHT / 2}
                stroke="#e5e7eb"
                strokeWidth={1}
              />

              {step && step.startedAt && (
                <StepBar
                  step={step}
                  y={y}
                  minTs={minTs}
                  totalDuration={totalDuration}
                  chartWidth={chartWidth}
                  labelWidth={LABEL_WIDTH}
                  chartPadding={CHART_PADDING}
                  stepKey={stepKey}
                />
              )}
            </g>
          );
        })}

        <text
          x={LABEL_WIDTH}
          y={svgHeight - 4}
          className="text-[10px] fill-gray-400"
          style={{ fontSize: "10px" }}
        >
          {formatAxisTime(minTs)}
        </text>
        <text
          x={svgWidth - CHART_PADDING}
          y={svgHeight - 4}
          textAnchor="end"
          className="text-[10px] fill-gray-400"
          style={{ fontSize: "10px" }}
        >
          {formatAxisTime(maxTs)}
        </text>
      </svg>
    </div>
  );
}

function StepBar({
  step,
  y,
  minTs,
  totalDuration,
  chartWidth,
  labelWidth,
  chartPadding,
  stepKey,
}: {
  step: StepStatus;
  y: number;
  minTs: number;
  totalDuration: number;
  chartWidth: number;
  labelWidth: number;
  chartPadding: number;
  stepKey: string;
}) {
  const startMs = new Date(step.startedAt!).getTime();
  const endMs = step.completedAt
    ? new Date(step.completedAt).getTime()
    : step.status === "running"
      ? Date.now()
      : startMs + 500;

  const startPct = (startMs - minTs) / totalDuration;
  const endPct = (endMs - minTs) / totalDuration;
  const barX = labelWidth + chartPadding + startPct * chartWidth;
  const barW = Math.max((endPct - startPct) * chartWidth, MIN_BAR_WIDTH);

  const fill = BAR_COLORS[step.status];
  const isRunning = step.status === "running";

  return (
    <g data-testid={`timeline-bar-${stepKey}`}>
      <rect
        x={barX}
        y={y}
        width={barW}
        height={BAR_HEIGHT}
        rx={4}
        fill={fill}
        opacity={0.85}
      />
      {isRunning && (
        <rect
          x={barX + barW - 3}
          y={y}
          width={3}
          height={BAR_HEIGHT}
          rx={1}
          fill={fill}
          opacity={1}
        >
          <animate
            attributeName="opacity"
            values="1;0.3;1"
            dur="1s"
            repeatCount="indefinite"
          />
        </rect>
      )}
    </g>
  );
}
