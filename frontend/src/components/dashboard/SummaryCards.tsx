"use client";

import type { QualitySummary } from "@/types/curation";

interface Props {
  summary: QualitySummary;
}

function healthColor(score: number | null): string {
  if (score === null) return "text-gray-400";
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-yellow-600";
  return "text-red-600";
}

function confidenceColor(val: number | null): string {
  if (val === null) return "text-gray-400";
  if (val >= 0.7) return "text-green-600";
  if (val >= 0.5) return "text-yellow-600";
  return "text-red-600";
}

function Card({
  label,
  value,
  colorClass,
  subtitle,
}: {
  label: string;
  value: string;
  colorClass: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </p>
      <p className={`mt-2 text-2xl font-bold ${colorClass}`}>{value}</p>
      {subtitle && (
        <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
      )}
    </div>
  );
}

export default function SummaryCards({ summary }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      <Card
        label="Total Ontologies"
        value={String(summary.ontology_count)}
        colorClass="text-gray-900"
      />
      <Card
        label="Avg Health Score"
        value={summary.avg_health_score !== null ? String(summary.avg_health_score) : "N/A"}
        colorClass={healthColor(summary.avg_health_score)}
        subtitle="0-100 composite"
      />
      <Card
        label="Avg Confidence"
        value={summary.avg_confidence !== null ? summary.avg_confidence.toFixed(2) : "N/A"}
        colorClass={confidenceColor(summary.avg_confidence)}
        subtitle="7-signal blend"
      />
      <Card
        label="Avg Faithfulness"
        value={summary.avg_faithfulness !== null ? summary.avg_faithfulness.toFixed(2) : "N/A"}
        colorClass={confidenceColor(summary.avg_faithfulness)}
        subtitle="LLM-as-judge grounding"
      />
      <Card
        label="Avg Semantic Validity"
        value={summary.avg_semantic_validity !== null ? summary.avg_semantic_validity.toFixed(2) : "N/A"}
        colorClass={confidenceColor(summary.avg_semantic_validity)}
        subtitle="OWL logical consistency"
      />
      <Card
        label="Avg Completeness"
        value={`${summary.avg_completeness.toFixed(0)}%`}
        colorClass={summary.avg_completeness >= 70 ? "text-green-600" : summary.avg_completeness >= 50 ? "text-yellow-600" : "text-red-600"}
        subtitle="Classes with properties"
      />
    </div>
  );
}
