/**
 * Class context-menu builder.
 *
 * Right-click on a class node in the Sigma / box-arrow canvas. Mirrors the
 * inventory in ``ui-architecture.mdc`` §7 ("Class node"):
 *
 *   View Details · Approve · Reject · View Version History · View Provenance · Delete
 *
 * Behaviour-preserving extraction from the original switch in
 * ``app/workspace/page.tsx`` (lines 727–787 pre-refactor). The native
 * ``confirm()`` for delete is retained until the H.6 PR replaces it with a
 * ConfirmDialog.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api } from "@/lib/api-client";

import type { WorkspaceContextMenuActions } from "./types";

export function buildClassContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const classKey = (data._key ?? data.key) as string;
  const classLabel = (data.label ?? classKey) as string;

  return [
    {
      label: "View Details",
      icon: "🔍",
      onClick: () => {
        actions.handleNodeSelect(classKey);
      },
    },
    { label: "separator0", separator: true },
    {
      label: "Approve",
      icon: "✅",
      onClick: () => {
        actions.approveClass(classKey);
      },
    },
    {
      label: "Reject",
      icon: "❌",
      onClick: () => {
        actions.rejectClass(classKey);
      },
    },
    { label: "separator1", separator: true },
    {
      label: "View Version History",
      icon: "📜",
      onClick: async () => {
        try {
          const history = await api.get<Record<string, unknown>[]>(
            `/api/v1/ontology/class/${classKey}/history`,
          );
          actions.setInfoPanelItem({
            type: "ontology",
            data: { _key: classKey, name: classLabel, _history: history },
          });
        } catch {
          actions.handleNodeSelect(classKey);
        }
      },
    },
    {
      label: "View Provenance",
      icon: "🔗",
      onClick: async () => {
        try {
          const prov = await api.get<{ data: Record<string, unknown>[] }>(
            `/api/v1/ontology/class/${classKey}/provenance`,
          );
          actions.setInfoPanelItem({
            type: "ontology",
            data: { _key: classKey, name: classLabel, _provenance: prov.data },
          });
        } catch {
          actions.handleNodeSelect(classKey);
        }
      },
    },
    { label: "separator2", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      onClick: () => {
        if (
          confirm(
            `Delete class "${classLabel}"? This will expire the class and all connected edges.`,
          )
        ) {
          actions.deleteClass(classKey);
        }
      },
    },
  ];
}
