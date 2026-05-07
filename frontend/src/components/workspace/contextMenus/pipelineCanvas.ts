/**
 * Pipeline-canvas context-menu builder.
 *
 * Right-click on empty space inside the pipeline DAG. Mirrors
 * ``ui-architecture.mdc`` §7 ("Pipeline canvas"):
 *
 *   Fit All Nodes
 *   Center View
 *   (the rest are gated on a loaded run:)
 *   Copy Run ID · View Run Info · View Extracted Entities · Retry Run · Delete Run
 *
 * "View Run Info" uses ``api.get`` so that 4xx / 5xx responses surface
 * via ``console.error``, matching the run-row menu in ``./run.ts``. Prior
 * to this file, the pipeline-canvas equivalent used a raw
 * ``fetch(backendUrl(...)) + res.ok`` check that swallowed 4xx silently;
 * the behaviour now matches the run menu.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api } from "@/lib/api-client";

import type { WorkspaceContextMenuActions } from "./types";

export function buildPipelineCanvasContextMenu(
  _data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const items: ContextMenuItem[] = [
    {
      label: "Fit All Nodes",
      icon: "⬜",
      onClick: () => {
        actions.closeContextMenu();
        actions.fitPipelineView();
      },
    },
    {
      label: "Center View",
      icon: "🎯",
      onClick: () => {
        actions.closeContextMenu();
        actions.centerPipelineView();
      },
    },
  ];

  const runId = actions.pipelineRunId;
  if (runId) {
    items.push({ label: "sep0", separator: true });
    items.push({
      label: "Copy Run ID",
      icon: "📋",
      onClick: () => {
        navigator.clipboard.writeText(runId).catch(() => {});
      },
    });
    items.push({
      label: "View Run Info",
      icon: "ℹ️",
      onClick: async () => {
        try {
          const run = await api.get<Record<string, unknown>>(
            `/api/v1/extraction/runs/${runId}`,
          );
          actions.setInfoPanelItem({ type: "run", data: run });
        } catch (err) {
          console.error("Failed to load run info", err);
        }
      },
    });
    items.push({
      label: "View Extracted Entities",
      icon: "📊",
      onClick: async () => {
        try {
          const results = await api.get<Record<string, unknown>>(
            `/api/v1/extraction/runs/${runId}/results`,
          );
          actions.setInfoPanelItem({
            type: "run",
            data: { _key: runId, name: "Extracted Entities", ...results },
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
      onClick: () => {
        actions.retryRun(runId);
      },
    });
    items.push({
      label: "Delete Run",
      icon: "🗑️",
      danger: true,
      onClick: () => {
        if (confirm(`Delete run ${runId}? This cannot be undone.`)) {
          actions.deleteRun(runId);
        }
      },
    });
  }

  return items;
}
