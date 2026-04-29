/**
 * Six-dimensional quality model from the per-ontology quality dashboard (0–5 scale).
 * Faithfulness prefers avg_faithfulness (LLM judge on classes); falls back to avg_confidence
 * when faithfulness is not stored (legacy extractions).
 */

export interface PerOntologyQualityApiShape {
  ontology_id?: string;
  avg_confidence: number | null;
  avg_faithfulness?: number | null;
  avg_semantic_validity?: number | null;
  class_count: number;
  property_count: number;
  completeness: number;
  connectivity: number;
  relationship_count: number;
  orphan_count: number;
  has_cycles: boolean;
  health_score: number | null;
  acceptance_rate: number | null;
  schema_metrics?: Record<string, number> | null;
}

export interface QualityDimensionDescriptor {
  key: string;
  label: string;
  description: string;
  compute: (q: PerOntologyQualityApiShape) => number | null;
}

export const PER_ONTOLOGY_QUALITY_DIMENSIONS: QualityDimensionDescriptor[] = [
  {
    key: "annotation",
    label: "Annotation Quality",
    description:
      "Completeness of labels, descriptions, and comments on classes/properties",
    compute: (q) =>
      q.schema_metrics != null &&
      typeof q.schema_metrics.annotation_completeness === "number"
        ? q.schema_metrics.annotation_completeness * 5
        : null,
  },
  {
    key: "completeness",
    label: "Completeness",
    description: "Proportion of classes that have at least one property defined",
    compute: (q) => (q.completeness / 100) * 5,
  },
  {
    key: "faithfulness",
    label: "Faithfulness",
    description:
      "LLM-as-judge faithfulness on classes (falls back to mean extraction confidence if not recorded)",
    compute: (q) => {
      const v = q.avg_faithfulness ?? q.avg_confidence;
      return v != null ? v * 5 : null;
    },
  },
  {
    key: "connectivity",
    label: "Connectivity",
    description: "Ratio of classes linked by inter-class object properties",
    compute: (q) => (q.connectivity / 100) * 5,
  },
  {
    key: "structural",
    label: "Structural Integrity",
    description: "Absence of cycles and orphan classes in the hierarchy",
    compute: (q) => {
      const orphanRatio =
        q.class_count > 0 ? q.orphan_count / q.class_count : 0;
      return Math.max(0, (1 - orphanRatio - (q.has_cycles ? 0.3 : 0)) * 5);
    },
  },
  {
    key: "curation",
    label: "Curation Acceptance",
    description: "Proportion of extracted elements accepted by human curators",
    compute: (q) =>
      q.acceptance_rate != null ? q.acceptance_rate * 5 : null,
  },
];

export function scoreColor(score: number): string {
  if (score >= 3.5) return "text-green-600";
  if (score >= 2.0) return "text-yellow-600";
  return "text-red-600";
}

export function scoreBgColor(score: number): string {
  if (score >= 3.5) return "bg-green-50 border-green-200";
  if (score >= 2.0) return "bg-yellow-50 border-yellow-200";
  return "bg-red-50 border-red-200";
}

export function healthColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-yellow-600";
  return "text-red-600";
}

export function healthBgColor(score: number): string {
  if (score >= 70) return "bg-green-50 border-green-300";
  if (score >= 40) return "bg-yellow-50 border-yellow-300";
  return "bg-red-50 border-red-300";
}
