/**
 * Property context-menu builder.
 *
 * Right-click on a property row in the asset explorer / class detail. Mirrors
 * ``ui-architecture.mdc`` §7 ("Property"): View · Approve · Reject · Copy URI.
 *
 * Approve / Reject reflect server-side state via the ``status`` payload on the
 * row; the matching button is disabled when that state is already in effect to
 * prevent no-op writes.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";

import type { WorkspaceContextMenuActions } from "./types";

export function buildPropertyContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const propKey = (data._key ?? data.key) as string;
  const propLabel = (data.label ?? propKey) as string;
  const propOntologyId = (data.ontology_id ?? actions.selectedOntologyId) as string;
  const propRange = (data.range_datatype
    ?? data.range
    ?? (data.target_class as Record<string, unknown> | undefined)?.label
    ?? "") as string;
  const propStatus = data.status as string | undefined;

  return [
    {
      label: propLabel,
      icon: "🔍",
      onClick: () => {
        actions.setInfoPanelItem({
          type: "run",
          data: {
            _key: propKey,
            name: propLabel,
            status: propStatus,
            range: propRange,
            ontology_id: propOntologyId,
            ...data,
          },
        });
      },
    },
    { label: "separator0", separator: true },
    {
      label: "Approve",
      icon: "✅",
      disabled: propStatus === "approved",
      onClick: () => {
        actions.approveProperty(propKey, propOntologyId);
      },
    },
    {
      label: "Reject",
      icon: "❌",
      disabled: propStatus === "rejected",
      onClick: () => {
        actions.rejectProperty(propKey, propOntologyId);
      },
    },
    { label: "separator1", separator: true },
    {
      label: "Copy URI",
      icon: "📋",
      disabled: !data.uri,
      onClick: () => {
        if (data.uri) {
          navigator.clipboard.writeText(data.uri as string).catch(() => {});
        }
      },
    },
  ];
}
