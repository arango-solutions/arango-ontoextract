/**
 * Edge context-menu builder.
 *
 * Right-click on an edge in the graph canvas. Mirrors the workspace rule
 * §16 ("Edges are first-class — selection, detail panel, context actions,
 * API mutations, and legend rules that apply to nodes apply to edges") and
 * the inventory in ``ui-architecture.mdc`` §7 ("Edge"):
 *
 *   View details · Approve · Reject · View Version History · View Provenance · Delete
 *
 * History and Provenance are unlocked by ``GET /api/v1/ontology/edge/{edge_key}/history``
 * and ``GET /api/v1/ontology/edge/{edge_key}/provenance`` (PRD §7.3, parallel to
 * the existing class endpoints — see ``backend/app/api/ontology.py``). When
 * either fetch fails (404, network error) we fall back to opening the
 * read-only detail panel so right-click never feels broken.
 *
 * Behaviour-preserving extraction from the original switch in
 * ``app/workspace/page.tsx``.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api } from "@/lib/api-client";

import type { WorkspaceContextMenuActions } from "./types";

export function buildEdgeContextMenu(
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  const edgeKey = (data._key ?? data.key) as string;
  const edgeLabel = (data.label ?? data.edgeType ?? edgeKey) as string;
  const isImported = data.is_imported === true;
  const sourceOntologyId = (data.source_ontology_id as string | null | undefined) ?? null;
  const sourceOntologyName =
    (data.source_ontology_name as string | null | undefined) ?? null;

  const viewDetails: ContextMenuItem = {
    label: `${edgeLabel}`,
    icon: "🔍",
    onClick: () => {
      actions.handleEdgeSelect(edgeKey);
      actions.setDetailPanelOpen(true);
    },
  };

  const viewHistory: ContextMenuItem = {
    label: "View Version History",
    icon: "📜",
    onClick: async () => {
      try {
        const history = await api.get<Record<string, unknown>[]>(
          `/api/v1/ontology/edge/${edgeKey}/history`,
        );
        // ``AssetInfoPanel`` switches on ``_history`` (and ``_provenance``)
        // generically — see ``app/workspace/page.tsx`` lines 1276–1296. We
        // reuse ``type: "ontology"`` so the same renderer picks it up; the
        // panel header just shows whatever ``name`` we pass.
        actions.setInfoPanelItem({
          type: "ontology",
          data: { _key: edgeKey, name: edgeLabel, _history: history },
        });
      } catch {
        actions.handleEdgeSelect(edgeKey);
        actions.setDetailPanelOpen(true);
      }
    },
  };

  const viewProvenance: ContextMenuItem = {
    label: "View Provenance",
    icon: "🔗",
    onClick: async () => {
      try {
        const prov = await api.get<{ data: Record<string, unknown>[] }>(
          `/api/v1/ontology/edge/${edgeKey}/provenance`,
        );
        actions.setInfoPanelItem({
          type: "ontology",
          data: { _key: edgeKey, name: edgeLabel, _provenance: prov.data },
        });
      } catch {
        actions.handleEdgeSelect(edgeKey);
        actions.setDetailPanelOpen(true);
      }
    },
  };

  // Imported edges (Stream 1 H.15) — drop the mutating section and
  // surface "Open Source Ontology" instead. Same reasoning as the
  // ``class`` builder: Approve / Reject / Delete are not the right
  // affordance when the edge is owned by another ontology.
  if (isImported) {
    const openLabel = sourceOntologyName
      ? `Open Source Ontology (${sourceOntologyName})`
      : "Open Source Ontology";
    // Stream 1 H.16: same blast-radius semantics as the class menu —
    // "Remove Import" drops the entire imports edge to the source
    // ontology, not just this one edge. Labelled with the source so the
    // user understands the scope.
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
    viewHistory,
    viewProvenance,
    { label: "separator2", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      disabled: true,
    },
  ];
}
