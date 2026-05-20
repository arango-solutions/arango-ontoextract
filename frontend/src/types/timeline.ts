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

export interface OntologyConstraint {
  _key?: string;
  _id?: string;
  constraint_type: string;
  on_class: string;
  property_id?: string | null;
  property_uri: string;
  restriction_type: string;
  restriction_value: number | string | boolean | null;
  description?: string;
  ontology_id: string;
  confidence?: number;
  created?: number;
  expired?: number;
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
