import type { StepStatus } from "@/types/pipeline";
import type { TimelineEvent } from "@/types/timeline";
import { STEP_LABELS, type PipelineStep } from "@/types/pipeline";

/**
 * Convert pipeline step statuses into synthetic TimelineEvents so the VCR
 * timeline has individual ticks at each step boundary.  This lets scrubbing
 * show gradual state transitions instead of jumping from "all pending" to
 * "all completed" in one tick.
 */
export function buildStepTimelineEvents(
  steps: Map<string, StepStatus>,
): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  steps.forEach((step, key) => {
    const label = STEP_LABELS[key as PipelineStep] ?? key;

    if (step.startedAt) {
      const ts = new Date(step.startedAt).getTime() / 1000;
      events.push({
        timestamp: ts,
        event_type: "step_started",
        entity_key: `step:${key}:started`,
        entity_label: label,
        collection: "pipeline_steps",
      });
    }

    if (step.completedAt) {
      const ts = new Date(step.completedAt).getTime() / 1000;
      events.push({
        timestamp: ts,
        event_type: "step_completed",
        entity_key: `step:${key}:completed`,
        entity_label: label,
        collection: "pipeline_steps",
      });
    }
  });

  return events;
}
