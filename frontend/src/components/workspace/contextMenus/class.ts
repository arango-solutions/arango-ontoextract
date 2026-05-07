/**
 * Class context-menu builder.
 *
 * Right-click on a class node in the Sigma / box-arrow canvas. Mirrors the
 * inventory in ``ui-architecture.mdc`` §7 ("Class node"):
 *
 *   View Details · Approve · Reject · View Version History · View Provenance · Delete
 *
 * Delete is technically reversible per ``ui-architecture.mdc`` §18 (a
 * server-side restore is conceivable: the temporal model expires rather
 * than hard-deletes), but the rule's preferred undo-toast pattern requires
 * deferred-delete + a global toast host that don't exist yet. For now,
 * Delete fires a plain ``ConfirmDialog`` via ``actions.requestConfirm`` —
 * which already removes the ``window.confirm`` call called out by
 * ``ui-architecture.mdc`` §18 ("Forbidden anywhere. No exceptions.").
 * The undo-toast migration is tracked as a follow-up.
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
        actions.requestConfirm({
          title: "Delete class",
          message: `Delete class "${classLabel}"?\nThis will expire the class and all connected edges.`,
          confirmLabel: "Delete",
          danger: true,
          onConfirm: () => actions.deleteClass(classKey),
        });
      },
    },
  ];
}
