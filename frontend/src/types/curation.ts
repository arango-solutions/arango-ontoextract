export type CurationStatus = "pending" | "approved" | "rejected";
export type CurationDecisionType = "approve" | "reject" | "edit" | "merge";
export type EdgeType =
  | "subclass_of"
  | "equivalent_class"
  | "has_property"
  | "extends_domain"
  | "related_to"
  | "extracted_from"
  | "imports";

export interface OntologyClass {
  _key: string;
  uri: string;
  label: string;
  description: string;
  rdf_type: string;
  confidence: number;
  status: CurationStatus;
  ontology_id: string;
  created: string;
  expired: string | null;
}

export interface OntologyProperty {
  _key: string;
  uri: string;
  label: string;
  description: string;
  domain_class: string;
  range_type: string;
  confidence: number;
  status: CurationStatus;
  ontology_id: string;
  created: string;
  expired: string | null;
}

export interface OntologyEdge {
  _key: string;
  _from: string;
  _to: string;
  type: EdgeType;
  label: string;
  confidence?: number;
  status?: CurationStatus;
  created?: string;
  expired?: string | null;
}

export interface CurationDecision {
  _key: string;
  run_id: string;
  entity_key: string;
  entity_type: "class" | "property" | "edge";
  decision: CurationDecisionType;
  curator_id: string;
  notes: string;
  created_at: string;
  before_state?: Record<string, unknown>;
  after_state?: Record<string, unknown>;
}

export interface StagingGraph {
  run_id: string;
  ontology_id?: string;
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
}

export interface SourceChunk {
  _key: string;
  document_id: string;
  document_name: string;
  text: string;
  page?: number;
  section?: string;
  start_char?: number;
  end_char?: number;
}

export interface PromotionResult {
  promoted_classes: number;
  promoted_properties: number;
  promoted_edges: number;
  errors: string[];
}

export interface BatchDecisionRequest {
  entity_keys: string[];
  entity_type: "class" | "property" | "edge";
  decision: CurationDecisionType;
  notes?: string;
}

export interface DiffEntry {
  entity_key: string;
  entity_type: "class" | "property" | "edge";
  change_type: "added" | "removed" | "changed";
  label: string;
  fields_changed?: string[];
}

export interface StagingVsProductionDiff {
  added: DiffEntry[];
  removed: DiffEntry[];
  changed: DiffEntry[];
}

export interface OntologyRegistryEntry {
  _key: string;
  name: string;
  description: string;
  tier: "domain" | "local";
  class_count: number;
  property_count: number;
  edge_count: number;
  last_updated?: string;
  updated_at?: string;
  created_at?: string;
  ontology_id: string;
  extraction_run_id?: string;
  source_document?: string;
  status: "draft" | "active" | "deprecated";
}
