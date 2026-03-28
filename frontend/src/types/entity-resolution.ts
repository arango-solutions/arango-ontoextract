export type MergeCandidateStatus = "pending" | "accepted" | "rejected";
export type SimilarityMethod =
  | "jaro_winkler"
  | "cosine"
  | "exact"
  | "jaccard"
  | "levenshtein";
export type ExtractionClassification = "EXISTING" | "EXTENSION" | "NEW";

export interface EntityRef {
  key: string;
  uri: string;
  label: string;
}

export interface FieldScores {
  label_sim: number;
  description_sim: number;
  uri_sim: number;
  topology_sim: number;
}

export interface MergeCandidate {
  pair_id: string;
  entity_1: EntityRef;
  entity_2: EntityRef;
  overall_score: number;
  field_scores: FieldScores;
  status: MergeCandidateStatus;
}

export interface ERCluster {
  cluster_id: string;
  entities: EntityRef[];
  golden_record_key: string | null;
}

export interface FieldExplanation {
  field_name: string;
  value_1: string;
  value_2: string;
  similarity: number;
  method: SimilarityMethod;
}

export interface MergeExplanation {
  pair_id: string;
  entity_1: EntityRef;
  entity_2: EntityRef;
  overall_score: number;
  fields: FieldExplanation[];
}

export interface EntityDetail {
  key: string;
  uri: string;
  label: string;
  description: string;
  rdf_type: string;
  properties: Record<string, string>;
  edges: { type: string; target_label: string; target_key: string }[];
}

export interface MergeRequest {
  pair_id: string;
  golden_record: {
    label: string;
    description: string;
    uri: string;
    properties: Record<string, string>;
  };
  surviving_entity_key: string;
}

export interface MergeResult {
  merged_key: string;
  merged_label: string;
  deprecated_keys: string[];
  edges_transferred: number;
}

export interface CrossTierDuplicate {
  pair_id: string;
  domain_entity: EntityRef;
  local_entity: EntityRef;
  overall_score: number;
  suggested_relation: "owl:equivalentClass" | "rdfs:subClassOf";
}
