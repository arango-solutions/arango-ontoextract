/**
 * Document context-menu builder.
 *
 * Right-click on a document row in the asset explorer. Mirrors
 * ``ui-architecture.mdc`` §7 ("Document"): View Info · Delete.
 *
 * Delete is reversible per §18 — the action fires immediately; the
 * downstream ``deleteDocument`` callback is responsible for the undo toast
 * (``confirm()`` is intentionally NOT called here, matching today's behaviour).
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";

import type { WorkspaceContextMenuActions } from "./types";

export function buildDocumentContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const docKey = data._key as string;

  return [
    {
      label: "View Info",
      icon: "📋",
      onClick: () => {
        actions.setInfoPanelItem({ type: "document", data });
      },
    },
    { label: "separator1", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      onClick: () => {
        actions.deleteDocument(docKey);
      },
    },
  ];
}
