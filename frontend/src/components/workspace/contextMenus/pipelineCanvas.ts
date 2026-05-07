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
 * Behaviour quirk preserved verbatim from ``app/workspace/page.tsx``:
 * "View Run Info" here uses raw ``fetch(backendUrl(...))`` with a quiet
 * ``res.ok`` check rather than the ``api.get`` helper used by the run /
 * step menus. That means 4xx responses fail silently here while they would
 * throw in the run menu. We deliberately keep the divergence so this
 * commit stays purely structural; harmonising the two is a follow-up.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api, backendUrl } from "@/lib/api-client";

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
          const res = await fetch(backendUrl(`/api/v1/extraction/runs/${runId}`));
          if (res.ok) {
            const run = await res.json();
            actions.setInfoPanelItem({ type: "run", data: run });
          }
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
