export type RunStatus = "queued" | "running" | "completed" | "failed" | "paused";

export type StepStatusValue =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "paused";

export interface StepStatus {
  status: StepStatusValue;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  data?: Record<string, unknown>;
}

export interface ExtractionRun {
  _key: string;
  document_id: string;
  document_name: string;
  ontology_id?: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  started_at?: number;
  completed_at?: number;
  duration_ms?: number;
  current_step?: string;
  chunk_count?: number;
  classes_extracted?: number;
  properties_extracted?: number;
  error_count?: number;
  model?: string;
  stats?: RunStats;
}

export interface RunStats {
  total_duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  estimated_cost?: number;
  classes_extracted?: number;
  properties_extracted?: number;
  pass_agreement_rate?: number;
  errors?: RunError[];
}

export interface RunError {
  timestamp: string;
  step: string;
  message: string;
  stack_trace?: string;
}

/**
 * IBR.12 -- belief-revision summary persisted on `extraction_runs.stats`
 * and surfaced through `GET /api/v1/extraction/runs/{id}/cost`.
 *
 * `null` (or the field omitted) means the IBR agent never ran on this
 * run -- either because it pre-dates Stream 11, or because the
 * pipeline crashed before the IBR node fired. The Pipeline Monitor
 * renders that as a neutral "no data" tile rather than misleading
 * zeros.
 *
 * A populated payload always carries `status` and (when relevant)
 * `reason`, letting the UI distinguish:
 *   * `status === "completed"` -- the IBR phase ran end to end and
 *     the counts are real.
 *   * `status === "skipped"`   -- the phase no-op'd and `reason`
 *     explains why (e.g. `feature_flag_off`,
 *     `no_extraction_results`, `no_ontology_id`,
 *     `no_document_id`).
 *   * `status === "failed"`    -- the phase blew up; counts are
 *     whatever progress was made before the failure.
 */
export interface BeliefRevisionSummary {
  status: "completed" | "skipped" | "failed";
  reason?: string;
  touchpoints_discovered: number;
  verdict_counts: Record<string, number>;
  auto_applied: number;
  flagged_for_curation: number;
  llm_invocations: number;
  skipped_idempotency: number;
}

export interface RunCostResponse {
  run_id: string;
  total_duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  classes_extracted: number;
  properties_extracted: number;
  pass_agreement_rate: number;
  model_breakdown?: ModelCost[];
  avg_confidence?: number | null;
  completeness_pct?: number | null;
  belief_revision?: BeliefRevisionSummary | null;
}

export interface ModelCost {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number;
}

export type WebSocketEventType =
  | "step_started"
  | "step_completed"
  | "step_failed"
  | "pipeline_paused"
  | "completed";

export interface WebSocketEvent {
  type: WebSocketEventType;
  step?: string;
  data?: Record<string, unknown>;
  timestamp: string;
  error?: string;
}

export const PIPELINE_STEPS = [
  "strategy_selector",
  "extraction_agent",
  "consistency_checker",
  "quality_judge",
  "entity_resolution_agent",
  "pre_curation_filter",
] as const;

export type PipelineStep = (typeof PIPELINE_STEPS)[number];

export const STEP_LABELS: Record<PipelineStep, string> = {
  strategy_selector: "Strategy Selector",
  extraction_agent: "Extraction Agent",
  consistency_checker: "Consistency Checker",
  quality_judge: "Quality Judge",
  entity_resolution_agent: "Entity Resolution Agent",
  pre_curation_filter: "Pre-Curation Filter",
};
