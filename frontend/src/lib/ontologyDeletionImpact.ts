/**
 * H.4 — Typed client for ``GET /api/v1/ontology/library/{id}/deletion-impact``.
 *
 * The backend service ``app/services/ontology_dependency.py`` produces this
 * payload; the ``OntologyDeleteDialog`` component consumes it. Keeping the
 * shape in one TypeScript file avoids drift across the dialog, its tests,
 * and any future surface (e.g. the dashboard "Released" column or a CLI).
 */

import { api } from "@/lib/api-client";

/** A single row in either ``direct_dependents`` or ``imports_outgoing``. */
export interface DependentOntology {
  _key: string;
  name: string;
  status?: string | null;
}

/** A single row in ``transitive_dependents``. ``depth`` is the number of
 *  ``imports`` hops away (1 = direct dependent). */
export interface TransitiveDependent extends DependentOntology {
  depth: number;
}

/** Per-collection counts of live entities the cascade would soft-expire.
 *  Backend always emits a row per known collection (zero when empty) so
 *  the table renders with stable shape. */
export type ExpireCounts = Record<string, number>;

export interface ExtractionRunSummary {
  /** Runs whose ``target_ontology_id`` is the ontology being deleted. */
  as_target: number;
  /** Runs that reference the ontology in ``domain_ontology_ids``. */
  as_domain: number;
  /** Deduped union of the two (a single run can appear in both buckets). */
  total: number;
}

export interface OntologyDeletionImpact {
  ontology_id: string;
  ontology_name: string;
  status?: string | null;
  direct_dependents: DependentOntology[];
  transitive_dependents: TransitiveDependent[];
  imports_outgoing: DependentOntology[];
  cross_ontology_extends_edges: number;
  expire_counts: ExpireCounts;
  extraction_runs: ExtractionRunSummary;
  quality_history_snapshots: number;
  released_versions: number;
  open_revisions: number;
  has_dependents: boolean;
  /** True iff no upstream dependents AND no cross-ontology edges AND
   *  no released versions exist. The frontend should still require
   *  the typed-name confirmation when ``false``. */
  safe_to_delete: boolean;
  /** Human-readable strings, one per concern -- render as a list above
   *  the typed-name input. */
  warnings: string[];
}

/** Fetch the cascade-on-delete dependency analysis for an ontology.
 *  Throws ``ApiError`` (404) if the ontology does not exist. */
export async function fetchOntologyDeletionImpact(
  ontologyId: string,
): Promise<OntologyDeletionImpact> {
  return api.get<OntologyDeletionImpact>(
    `/api/v1/ontology/library/${encodeURIComponent(ontologyId)}/deletion-impact`,
  );
}
