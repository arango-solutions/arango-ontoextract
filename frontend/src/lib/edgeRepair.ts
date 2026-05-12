/**
 * Typed wrapper for the edge-repair admin endpoint.
 *
 * Mirrors :class:`backend.app.services.edge_repair.RepairReport` exactly --
 * a single source of truth for the JSON shape the workspace overlay
 * renders. Two operations:
 *
 * - :func:`previewEdgeRepair` (``dry_run=true``) lists the would-be
 *   repairs without writing anything; safe to call repeatedly.
 * - :func:`applyEdgeRepair` (``dry_run=false``) inserts the missing
 *   ``rdfs_range_class`` edges. Idempotent on the server side: a second
 *   call after a successful run returns ``orphans_found == 0``.
 *
 * The endpoint returns a full ``RepairReport``; we don't trim it here so
 * the overlay can show post-apply counts ("repaired 18 of 23") without
 * having to track them client-side.
 */

import { api } from "@/lib/api-client";

export interface RepairedEdge {
  prop_key: string;
  domain_class_key: string;
  range_class_key: string;
  matched_text: string;
  matched_via: string;
  other_candidates: string[];
}

export interface UnrecoverableOrphan {
  prop_key: string;
  domain_class_key: string | null;
  label: string;
  description: string;
}

export interface EdgeRepairReport {
  ontology_id: string;
  orphans_found: number;
  repaired_count: number;
  unrecoverable_count: number;
  no_domain_count: number;
  repaired: RepairedEdge[];
  unrecoverable: UnrecoverableOrphan[];
  no_domain: string[];
}

function endpoint(ontologyId: string, dryRun: boolean): string {
  const id = encodeURIComponent(ontologyId);
  const q = dryRun ? "?dry_run=true" : "";
  return `/api/v1/admin/ontology/${id}/repair-edges${q}`;
}

/** Dry-run: returns the would-be repairs without modifying the graph. */
export async function previewEdgeRepair(
  ontologyId: string,
): Promise<EdgeRepairReport> {
  return api.post<EdgeRepairReport>(endpoint(ontologyId, true));
}

/** Apply: inserts the missing ``rdfs_range_class`` edges; idempotent. */
export async function applyEdgeRepair(
  ontologyId: string,
): Promise<EdgeRepairReport> {
  return api.post<EdgeRepairReport>(endpoint(ontologyId, false));
}
