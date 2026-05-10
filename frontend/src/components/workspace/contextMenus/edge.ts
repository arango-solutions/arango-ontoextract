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
    },
    {
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
    },
    { label: "separator2", separator: true },
    {
      label: "Delete",
      icon: "🗑️",
      danger: true,
      disabled: true,
    },
  ];
}
