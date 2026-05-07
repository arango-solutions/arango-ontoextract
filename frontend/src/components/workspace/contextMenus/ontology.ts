/**
 * Ontology context-menu builder.
 *
 * Right-click on an ontology row in the asset explorer. Mirrors
 * ``ui-architecture.mdc`` §7 ("Ontology"): Open in Canvas · View Info ·
 * Edit Name & Description · Release · Manage Imports · View Quality Report ·
 * View Feedback Learning · Export (Turtle / JSON-LD / CSV) · Delete.
 *
 * Notes:
 *
 * - Delete uses ``ConfirmDialog``'s **typed-name** mode per
 *   ``ui-architecture.mdc`` §18: the cascade (classes / properties / edges /
 *   runs / quality history) is unbounded enough that real friction is
 *   warranted. The user must type the ontology's display name verbatim
 *   before Confirm enables.
 * - Release is gated by ``data.status === "deprecated"`` to match the
 *   existing UX (deprecated ontologies cannot be re-released without going
 *   through admin tooling).
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";

import type { WorkspaceContextMenuActions } from "./types";

export function buildOntologyContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const ontKey = String(data._key ?? data.ontology_id ?? "").trim();

  return [
    {
      label: "Open in Canvas",
      icon: "🔷",
      onClick: () => {
        if (ontKey) actions.handleSelectOntology(ontKey);
      },
    },
    {
      label: "View Info",
      icon: "ℹ️",
      onClick: () => {
        actions.setInfoPanelItem({ type: "ontology", data });
      },
    },
    {
      label: "Edit name & description",
      icon: "✏️",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        const d = typeof data.description === "string" ? data.description : "";
        actions.setRenameOntology({ key: ontKey, name: n || ontKey, description: d });
      },
    },
    {
      label: "Release",
      icon: "🚀",
      disabled: data.status === "deprecated",
      onClick: () => {
        if (!ontKey || data.status === "deprecated") return;
        const cur =
          typeof data.current_release_version === "string"
            ? data.current_release_version
            : null;
        actions.setReleaseOntology({ key: ontKey, currentReleaseVersion: cur });
      },
    },
    {
      label: "Manage Imports",
      icon: "🔗",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setManageImports({ key: ontKey, name: n });
      },
    },
    {
      label: "View Quality Report",
      icon: "📊",
      onClick: () => actions.fetchOntologyQualityReport(data),
    },
    {
      label: "View Feedback Learning",
      icon: "📊",
      onClick: () => {
        actions.setFeedbackLearning({
          ontologyId: ontKey || null,
          ontologyName: String(data.name ?? data.label ?? ontKey),
        });
      },
    },
    {
      label: "Export",
      icon: "📤",
      submenu: [
        {
          label: "Turtle (.ttl)",
          onClick: () => {
            if (ontKey) actions.exportOntology(ontKey, "turtle");
          },
        },
        {
          label: "JSON-LD",
          onClick: () => {
            if (ontKey) actions.exportOntology(ontKey, "jsonld");
          },
        },
        {
          label: "CSV",
          onClick: () => {
            if (ontKey) actions.exportOntology(ontKey, "csv");
          },
        },
      ],
    },
    { label: "separator1", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      onClick: () => {
        if (!ontKey) return;
        const displayName = String(data.name ?? data.label ?? ontKey).trim() || ontKey;
        actions.requestConfirm({
          title: "Delete ontology",
          message:
            `Delete ontology "${displayName}"?\n` +
            `This cascades to its classes, properties, edges, extraction runs, and ` +
            `quality history. This cannot be undone.`,
          confirmLabel: "Delete",
          danger: true,
          typedName: {
            expected: displayName,
            label: `Type the ontology name to confirm:`,
            placeholder: displayName,
          },
          onConfirm: () => actions.deleteOntology(ontKey),
        });
      },
    },
  ];
}
