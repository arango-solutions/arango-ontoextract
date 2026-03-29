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
  "entity_resolution_agent",
  "pre_curation_filter",
] as const;

export type PipelineStep = (typeof PIPELINE_STEPS)[number];

export const STEP_LABELS: Record<PipelineStep, string> = {
  strategy_selector: "Strategy Selector",
  extraction_agent: "Extraction Agent",
  consistency_checker: "Consistency Checker",
  entity_resolution_agent: "Entity Resolution Agent",
  pre_curation_filter: "Pre-Curation Filter",
};
