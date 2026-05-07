/**
 * Pipeline-step context-menu builder.
 *
 * Right-click on a step node in the pipeline DAG. Mirrors
 * ``ui-architecture.mdc`` §7 ("Pipeline step"): View Step Details ·
 * Copy Error · View Run Results · Retry Run.
 *
 * The menu is built **conditionally** based on the surrounding state:
 *
 * - Copy Error appears only when the step recorded an ``error`` payload.
 * - View Run Results and Retry Run appear only when ``actions.pipelineRunId``
 *   is set (i.e. the canvas is showing a pipeline rather than an ontology).
 * - Retry Run is disabled unless the step's status is ``failed`` —
 *   non-failed steps would re-run the whole pipeline mid-flight.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api } from "@/lib/api-client";

import type { WorkspaceContextMenuActions } from "./types";

export function buildStepContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const stepKey = data.stepKey as string;
  const stepLabel = data.label as string;
  const stepStatus = data.status as string;
  const stepError = data.error as string | undefined;
  const stepStartedAt = data.startedAt as string | undefined;
  const stepCompletedAt = data.completedAt as string | undefined;
  const stepData = data.data as Record<string, unknown> | undefined;
  const durationMs = stepData?.duration_ms as number | undefined;

  const items: ContextMenuItem[] = [
    {
      label: "View Step Details",
      icon: "🔍",
      onClick: () => {
        actions.setInfoPanelItem({
          type: "run",
          data: {
            _key: `step:${stepKey}`,
            name: stepLabel,
            status: stepStatus,
            started_at: stepStartedAt,
            completed_at: stepCompletedAt,
            duration_ms: durationMs,
            ...stepData,
          },
        });
      },
    },
  ];

  if (stepError) {
    items.push({
      label: "Copy Error",
      icon: "📋",
      onClick: () => {
        navigator.clipboard.writeText(stepError).catch(() => {});
      },
    });
  }

  items.push({ label: "sep0", separator: true });

  if (actions.pipelineRunId) {
    const runId = actions.pipelineRunId;
    items.push({
      label: "View Run Results",
      icon: "📊",
      onClick: async () => {
        try {
          const results = await api.get<Record<string, unknown>>(
            `/api/v1/extraction/runs/${runId}/results`,
          );
          actions.setInfoPanelItem({
            type: "run",
            data: {
              _key: runId,
              name: `Results — ${stepLabel}`,
              ...results,
            },
          });
        } catch (err) {
          console.error("Failed to load run results", err);
        }
      },
    });

    items.push({ label: "sep1", separator: true });

    items.push({
      label: "Retry Run",
      icon: "🔄",
      disabled: stepStatus !== "failed",
      onClick: () => {
        actions.retryRun(runId);
      },
    });
  }

  return items;
}
