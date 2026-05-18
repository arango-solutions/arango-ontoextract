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
 *
 * Imported classes (Stream 1 H.15)
 * --------------------------------
 *
 * When ``data.is_imported === true`` the class is owned by an imported
 * ontology, not the one currently open. We swap the menu inventory to:
 *
 *   View Details · View Version History · View Provenance · Open Source Ontology
 *
 * Mutating actions (Approve / Reject / Delete) are removed entirely
 * rather than disabled — leaving them present-but-greyed implies
 * "approve me here once you fix something", which is the wrong mental
 * model. The right move is to jump to the source ontology and curate
 * there. The deep-link target is ``data.source_ontology_id`` (forwarded
 * by ``SigmaCanvas``'s ``rightClickNode`` payload, originating from the
 * effective-graph endpoint's class annotation).
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
  const isImported = data.is_imported === true;
  const sourceOntologyId = (data.source_ontology_id as string | null | undefined) ?? null;
  const sourceOntologyName =
    (data.source_ontology_name as string | null | undefined) ?? null;

  const viewDetails: ContextMenuItem = {
    label: "View Details",
    icon: "🔍",
    onClick: () => {
      actions.handleNodeSelect(classKey);
    },
  };

  const viewHistory: ContextMenuItem = {
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
  };

  const viewProvenance: ContextMenuItem = {
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
  };

  if (isImported) {
    const openLabel = sourceOntologyName
      ? `Open Source Ontology (${sourceOntologyName})`
      : "Open Source Ontology";
    // Stream 1 H.16: "Remove Import" removes the entire ``imports``
    // edge to the source ontology — taking ALL imported entities off
    // the canvas at once, not just this one class. The label names the
    // source so the user knows the blast radius. We act immediately +
    // emit an undo toast (per ``ui-architecture.mdc`` §18) rather than
    // gating on a confirm dialog; the side-effect is reversible at
    // any time via Manage Imports if the user dismisses the toast.
    const removeLabel = sourceOntologyName
      ? `Remove Import (${sourceOntologyName})`
      : "Remove Import";
    return [
      viewDetails,
      { label: "separator0", separator: true },
      viewHistory,
      viewProvenance,
      { label: "separator1", separator: true },
      {
        label: openLabel,
        icon: "🔷",
        // Deep-link by switching the workspace selection. When the
        // ``source_ontology_id`` is missing (defensive — the wire format
        // always populates it for imported classes), we fall back to a
        // disabled hint so the user is not silently dropped on the
        // floor; in practice this branch never fires.
        disabled: !sourceOntologyId,
        onClick: () => {
          if (sourceOntologyId) {
            actions.handleSelectOntology(sourceOntologyId);
          }
        },
      },
      {
        label: removeLabel,
        icon: "🗑️",
        danger: true,
        disabled: !sourceOntologyId,
        onClick: () => {
          if (sourceOntologyId) {
            void actions.removeImportEdge(
              sourceOntologyId,
              sourceOntologyName ?? sourceOntologyId,
            );
          }
        },
      },
    ];
  }

  return [
    viewDetails,
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
    viewHistory,
    viewProvenance,
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
