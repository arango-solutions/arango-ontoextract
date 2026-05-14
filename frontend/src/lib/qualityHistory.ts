import { api } from "@/lib/api-client";

export interface QualityHistorySnapshot {
  _key?: string;
  ontology_id: string;
  timestamp: string;
  /**
   * Where the snapshot came from. Q.2 added event-tagged sources so
   * the trend chart can distinguish "user opened the report" from
   * "extraction completed" and "promotion happened":
   *   - "quality_api"           — recorded on each report view
   *   - "extraction_completion" — recorded after a successful extraction
   *   - "promotion"             — recorded after staging→production
   *   - "manual"                — operator/MCP triggered
   */
  source?: string;
  /** When source is "extraction_completion" or "promotion", this links
   *  the snapshot to the extraction run that caused it. */
  run_id?: string | null;
  health_score?: number | null;
  avg_confidence?: number | null;
  avg_faithfulness?: number | null;
  avg_semantic_validity?: number | null;
  completeness?: number | null;
  connectivity?: number | null;
  acceptance_rate?: number | null;
  expected_calibration_error?: number | null;
  class_count?: number | null;
  property_count?: number | null;
  relationship_count?: number | null;
  orphan_count?: number | null;
  has_cycles?: boolean | null;
}

export interface QualityHistoryResponse {
  ontology_id: string;
  count: number;
  snapshots: QualityHistorySnapshot[];
}

export async function loadQualityHistory(
  ontologyId: string,
  options: { limit?: number } = {},
): Promise<QualityHistoryResponse> {
  const params = new URLSearchParams();
  if (options.limit != null) params.set("limit", String(options.limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return api.get<QualityHistoryResponse>(
    `/api/v1/quality/${encodeURIComponent(ontologyId)}/history${suffix}`,
  );
}
