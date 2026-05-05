/**
 * Edge context-menu builder.
 *
 * Right-click on an edge in the graph canvas. Mirrors ``ui-architecture.mdc``
 * §7 ("Edge"): View details · Approve · Reject · Delete (disabled).
 *
 * Behaviour-preserving extraction from the original switch in
 * ``app/workspace/page.tsx``.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";

import type { WorkspaceContextMenuActions } from "./types";

export function buildEdgeContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const edgeKey = (data._key ?? data.key) as string;
  const edgeLabel = (data.label ?? data.edgeType ?? edgeKey) as string;

  return [
    {
      label: `${edgeLabel}`,
      icon: "🔍",
      onClick: () => {
        actions.handleEdgeSelect(edgeKey);
        actions.setDetailPanelOpen(true);
      },
    },
    { label: "separator0", separator: true },
    {
      label: "Approve edge",
      icon: "✅",
      onClick: () => {
        actions.approveEdge(edgeKey);
      },
    },
    {
      label: "Reject edge",
      icon: "❌",
      onClick: () => {
        actions.rejectEdge(edgeKey);
      },
    },
    { label: "separator1", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      disabled: true,
    },
  ];
}
