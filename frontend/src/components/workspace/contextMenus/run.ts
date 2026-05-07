/**
 * Run context-menu builder.
 *
 * Right-click on an extraction-run row in the asset explorer. Mirrors
 * ``ui-architecture.mdc`` §7 ("Run"): View Pipeline & Metrics · Copy Run ID ·
 * View Run Info · View Extracted Entities · Retry Run · Delete Run.
 *
 * Delete Run is irreversible (the run row, its steps, and its extracted
 * entities are hard-deleted). It uses the plain ``ConfirmDialog`` mode (no
 * typed-name gate) per ``ui-architecture.mdc`` §18: the cost of an
 * accidental click is bounded — runs are easy to re-create from the source
 * documents — so a single Cancel / red-Delete pair is the right
 * severity-proportional friction.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api } from "@/lib/api-client";

import type { WorkspaceContextMenuActions } from "./types";

export function buildRunContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const runKey = data._key as string;

  return [
    {
      label: "View Pipeline & Metrics",
      icon: "⚡",
      onClick: () => {
        actions.handleSelectRun(runKey);
      },
    },
    {
      label: "Copy Run ID",
      icon: "📋",
      onClick: () => {
        navigator.clipboard.writeText(runKey).catch(() => {});
      },
    },
    {
      label: "View Run Info",
      icon: "ℹ️",
      onClick: async () => {
        try {
          const run = await api.get<Record<string, unknown>>(
            `/api/v1/extraction/runs/${runKey}`,
          );
          actions.setInfoPanelItem({ type: "run", data: run });
        } catch (err) {
          console.error("Failed to load run info", err);
        }
      },
    },
    {
      label: "View Extracted Entities",
      icon: "📊",
      onClick: async () => {
        try {
          const results = await api.get<Record<string, unknown>>(
            `/api/v1/extraction/runs/${runKey}/results`,
          );
          actions.setInfoPanelItem({
            type: "run",
            data: { _key: runKey, name: "Extracted Entities", ...results },
          });
        } catch (err) {
          console.error("Failed to load run results", err);
        }
      },
    },
    { label: "separator", separator: true },
    {
      label: "Retry Run",
      icon: "🔄",
      onClick: () => {
        actions.retryRun(runKey);
      },
    },
    {
      label: "Delete Run",
      icon: "🗑️",
      danger: true,
      onClick: () => {
        actions.requestConfirm({
          title: "Delete run",
          message: `Delete run ${runKey}?\nThis cannot be undone.`,
          confirmLabel: "Delete",
          danger: true,
          onConfirm: () => actions.deleteRun(runKey),
        });
      },
    },
  ];
}
