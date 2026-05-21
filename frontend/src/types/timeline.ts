import type { OntologyClass, OntologyProperty, OntologyEdge } from "./curation";

export type TimelineEventType =
  | "created"
  | "edited"
  | "approved"
  | "rejected"
  | "promoted"
  | "merged"
  | "reverted"
  | "step_started"
  | "step_completed";

export interface TimelineEvent {
  timestamp: number;
  event_type: TimelineEventType;
  entity_key: string;
  entity_label: string;
  collection: string;
  curator_id?: string;
  extraction_run_id?: string;
  details?: Record<string, unknown>;
}

/**
 * One row from the ``ontology_constraints`` collection. Three sources
 * write into this shape and the type captures the union of fields they
 * each carry:
 *
 * * **Extraction (Stream 3 PR 1)** -- LLM-emitted; stamps
 *   ``extraction_run_id`` and an LLM-rated ``confidence`` < 1.
 * * **OWL import (Stream 3 PR 2)** -- ``import_source = "owl_restriction"``,
 *   ``confidence = 1.0``.
 * * **SHACL import (Stream 3 PR 3)** -- ``import_source = "shacl_shape"``,
 *   ``confidence = 1.0``, plus SHACL-specific ``severity`` (default
 *   ``"sh:Violation"``) and ``shape_iri``.
 *
 * The API endpoint ``GET /api/v1/ontology/library/{id}/constraints``
 * enriches each row with ``class_label`` + ``property_label`` (joined
 * server-side from the just-imported collections) so the UI can render
 * a constraint chip without a follow-up round-trip.
 *
 * ``restriction_value`` is intentionally polymorphic so all three
 * sources share one row shape:
 *
 * * cardinality kinds -> ``number``
 * * datatype / class / hasValue / pattern / nodeKind -> ``string``
 * * ``sh:in`` enumeration -> ``string[]``
 * * (rare) extraction-time boolean -> ``boolean``
 */
export interface OntologyConstraint {
  _key?: string;
  _id?: string;
  constraint_type: string;
  on_class: string;
  property_id?: string | null;
  property_uri: string;
  restriction_type: string;
  restriction_value: number | string | boolean | string[] | null;
  description?: string;
  ontology_id: string;
  confidence?: number;
  created?: number;
  expired?: number;

  // PR 2 + PR 3 provenance marker. Distinguishes import-sourced rows
  // (``"owl_restriction"`` / ``"shacl_shape"``) from extraction rows
  // (which have ``extraction_run_id`` instead).
  import_source?: string;
  extraction_run_id?: string;

  // PR 3 SHACL-specific metadata. Always present on shacl_shape rows,
  // absent otherwise.
  severity?: string;
  shape_iri?: string;

  // Server-side API enrichment (joined from ontology_classes /
  // ontology_*_properties). Empty string when the corresponding id
  // couldn't be resolved.
  class_label?: string;
  property_label?: string;

  // Evidence array from extraction (PR 1). Empty for import-sourced rows.
  evidence?: Array<Record<string, unknown>>;
}

export interface TemporalSnapshot {
  ontology_id: string;
  timestamp: string;
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
  constraints?: OntologyConstraint[];
}

export interface TemporalDiff {
  t1: string;
  t2: string;
  added: TemporalDiffEntry[];
  removed: TemporalDiffEntry[];
  changed: TemporalDiffEntry[];
}

export interface TemporalDiffEntry {
  entity_key: string;
  entity_type: "class" | "property" | "edge";
  label: string;
  fields_changed?: string[];
  old_value?: Record<string, unknown>;
  new_value?: Record<string, unknown>;
}

export interface VersionEntry {
  version_number: number;
  data: Record<string, unknown>;
  created: string;
  expired: string | null;
}

export interface VersionHistory {
  class_key: string;
  uri: string;
  label: string;
  versions: VersionEntry[];
}
