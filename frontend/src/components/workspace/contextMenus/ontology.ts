/**
 * Ontology context-menu builder.
 *
 * Right-click on an ontology row in the asset explorer. Mirrors
 * ``ui-architecture.mdc`` §7 ("Ontology"): Open in Canvas · View Info ·
 * Edit Name & Description · Release · Manage Imports ·
 * View Dependency Graph · View Quality Report ·
 * View Feedback Learning · Export (Turtle / JSON-LD / CSV) · Delete.
 *
 * Notes:
 *
 * - Delete opens the dedicated ``OntologyDeleteDialog`` (Stream 1 H.4)
 *   instead of a bare typed-name ``ConfirmDialog``. The new dialog
 *   fetches ``GET /library/{id}/deletion-impact`` so the user sees the
 *   transitive ``imports`` dependents, cross-ontology ``extends_domain``
 *   edges, and per-collection expire counts BEFORE typing the ontology
 *   name to confirm. Per ``ui-architecture.mdc`` §18 the typed-name gate
 *   is preserved -- ontology deletion is irreversible enough to warrant
 *   real friction even after the impact preview.
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
      label: "View Dependency Graph…",
      icon: "🔗",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setDependencyOverlay({ key: ontKey, name: n || ontKey });
      },
    },
    {
      label: "Compare Schema Evolution…",
      icon: "📊",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setSchemaDiffOverlay({ key: ontKey, name: n || ontKey });
      },
    },
    {
      label: "View Quality Report",
      icon: "📊",
      onClick: () => actions.fetchOntologyQualityReport(data),
    },
    {
      // Stream 22: author competency questions + run coverage (overlay §9).
      label: "Requirements & Coverage…",
      icon: "✅",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setRequirementsOverlay({ key: ontKey, name: n || ontKey });
      },
    },
    {
      // Stream 21: A-box instance lens (overlay §9).
      label: "View Instances (A-box)…",
      icon: "📎",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setIndividualsOverlay({ key: ontKey, name: n || ontKey });
      },
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
      label: "Repair Orphan Properties…",
      icon: "🔧",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setEdgeRepair({ key: ontKey, name: n || ontKey });
      },
    },
    {
      label: "Show Pending Revisions",
      icon: "📨",
      onClick: () => {
        if (!ontKey) return;
        const n = String(data.name ?? data.label ?? ontKey).trim();
        actions.setRevisionsInbox({ key: ontKey, name: n || ontKey });
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
        // H.4: open the dedicated dialog so the user sees the cascade
        // dependency analysis before being asked to type the ontology
        // name. The dialog itself enforces the typed-name gate and
        // calls ``actions.deleteOntology`` only after Confirm.
        actions.setOntologyDelete({ key: ontKey, name: displayName });
      },
    },
  ];
}
