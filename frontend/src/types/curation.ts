export type CurationStatus = "pending" | "approved" | "rejected";
export type CurationDecisionType = "approve" | "reject" | "edit" | "merge";
export type EdgeType =
  | "subclass_of"
  | "equivalent_class"
  | "has_property"
  | "rdfs_domain"
  | "rdfs_range_class"
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
  /** Domain vs local tier — used by workspace "Source type" lens when present */
  tier?: string;
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
  /** Display name; file-import entries may only have ``label`` until normalized server-side. */
  name?: string;
  label?: string;
  description?: string;
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
  tags?: string[];
  health_score?: number;
}

export interface SearchResult {
  _key: string;
  label?: string;
  name?: string;
  description?: string;
  ontology_id?: string;
  ontology_name?: string;
  tier?: string;
  status?: string;
  tags?: string[];
  confidence?: number;
  domain_class?: string;
  score: number;
  source: "registry" | "class" | "property";
}

export interface SearchResponse {
  query: string;
  results: {
    registry: SearchResult[];
    classes: SearchResult[];
    properties: SearchResult[];
  };
  counts: {
    registry: number;
    classes: number;
    properties: number;
  };
  offset: number;
  limit: number;
}

/* ── Quality Dashboard Types ─────────────────────────── */

export interface QualitySummary {
  ontology_count: number;
  total_classes: number;
  total_properties: number;
  avg_faithfulness: number | null;
  avg_semantic_validity: number | null;
  avg_completeness: number;
  avg_health_score: number | null;
  ontologies_with_cycles: number;
  total_orphans: number;
}

export interface SchemaMetrics {
  relationship_richness: number;
  attribute_richness: number;
  max_depth: number;
  annotation_completeness: number;
}

export interface OntologyScorecard {
  ontology_id: string;
  name: string;
  tier: string;
  health_score: number | null;
  avg_confidence: number | null;
  avg_faithfulness: number | null;
  avg_semantic_validity: number | null;
  completeness: number;
  connectivity: number;
  relationship_count: number;
  class_count: number;
  property_count: number;
  orphan_count: number;
  has_cycles: boolean;
  classes_without_properties: number;
  estimated_cost: number | null;
  schema_metrics: SchemaMetrics | null;
}

export interface DashboardAlert {
  ontology_id: string;
  name: string;
  flag: string;
  severity: "red" | "yellow";
}

export interface QualityDashboard {
  summary: QualitySummary;
  ontologies: OntologyScorecard[];
  alerts: DashboardAlert[];
}

export interface QualitativeEvaluation {
  strengths: string[];
  weaknesses: string[];
  status?: string;
}

export interface ClassScore {
  _key: string;
  uri: string;
  label: string;
  confidence: number | null;
  faithfulness_score: number | null;
  semantic_validity_score: number | null;
}

