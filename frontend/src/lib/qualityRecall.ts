/**
 * Q.4 — Typed client for ``POST /api/v1/quality/recall``.
 *
 * The backend accepts the reference body as a string (not multipart);
 * the frontend reads the user-selected file with ``FileReader`` and
 * sends the text directly. Format hint is derived from the filename
 * extension when not overridden.
 */

import { api } from "@/lib/api-client";

export interface RecallSummary {
  reference_count: number;
  extracted_count: number;
  matched_count: number;
  recall: number;
  precision: number;
  f1: number;
}

export interface RecallSectionSummary {
  reference_count: number;
  extracted_count: number;
  matched_count: number;
}

export interface RecallMatchedPair {
  reference_uri: string;
  reference_label: string;
  extracted_uri: string | null;
  extracted_label: string | null;
  extracted_key: string | null;
  similarity: number;
}

export interface RecallMissed {
  reference_uri: string;
  reference_label: string;
}

export interface RecallFalsePositive {
  extracted_uri: string | null;
  extracted_label: string | null;
  extracted_key: string | null;
}

export interface RecallSection {
  summary: RecallSectionSummary;
  matched: RecallMatchedPair[];
  missed: RecallMissed[];
  false_positives: RecallFalsePositive[];
}

export interface RecallReport {
  ontology_id: string;
  match_threshold: number;
  rdf_format: string;
  summary: RecallSummary;
  classes: RecallSection;
  object_properties?: RecallSection;
}

export type RdfFormat = "turtle" | "xml" | "nt" | "json-ld";

export function inferRdfFormatFromFilename(filename: string): RdfFormat {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".ttl")) return "turtle";
  if (lower.endsWith(".owl") || lower.endsWith(".rdf") || lower.endsWith(".xml")) {
    return "xml";
  }
  if (lower.endsWith(".nt")) return "nt";
  if (lower.endsWith(".jsonld") || lower.endsWith(".json-ld")) return "json-ld";
  return "turtle";
}

export interface RecallRequestBody {
  ontology_id: string;
  reference_content: string;
  rdf_format?: RdfFormat;
  match_threshold?: number;
  include_object_properties?: boolean;
}

export async function computeQualityRecall(
  body: RecallRequestBody,
): Promise<RecallReport> {
  return api.post<RecallReport>("/api/v1/quality/recall", body);
}
