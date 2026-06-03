"use client";

import { confidenceColor as scoreColor } from "@/lib/thresholds";
import type { OntologyScorecard } from "@/types/curation";

interface Props {
  ontology: OntologyScorecard;
}

function MetricCard({
  label,
  value,
  description,
  colorClass,
}: {
  label: string;
  value: string;
  description: string;
  colorClass: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-start justify-between">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          {label}
        </p>
      </div>
      <p className={`mt-1.5 text-xl font-bold ${colorClass}`}>{value}</p>
      <p className="mt-1 text-xs text-gray-400 leading-relaxed">{description}</p>
    </div>
  );
}

export default function MetricCards({ ontology }: Props) {
  // Prefer the backend's structural_integrity (Stream 15 SO.2, single source of
  // truth). Fall back to the client formula for older payloads that predate it.
  const structuralIntegrity =
    ontology.structural_integrity != null
      ? ontology.structural_integrity
      : (() => {
          const cyclePenalty = ontology.has_cycles ? 0.3 : 0;
          const orphanRatio =
            ontology.class_count > 0 ? ontology.orphan_count / ontology.class_count : 0;
          return Math.max(0, 1.0 - cyclePenalty - orphanRatio);
        })();

  const islandCount = ontology.island_count ?? 0;

  return (
    <div className="grid grid-cols-2 gap-3">
      <MetricCard
        label="Faithfulness"
        value={ontology.avg_faithfulness !== null ? ontology.avg_faithfulness.toFixed(2) : "N/A"}
        description="Grounded in source documents"
        colorClass={scoreColor(ontology.avg_faithfulness)}
      />
      <MetricCard
        label="Completeness"
        value={`${ontology.completeness.toFixed(0)}%`}
        description="Classes with properties"
        colorClass={scoreColor(ontology.completeness / 100)}
      />
      <MetricCard
        label="Semantic Validity"
        value={ontology.avg_semantic_validity !== null ? ontology.avg_semantic_validity.toFixed(2) : "N/A"}
        description="OWL logical consistency"
        colorClass={scoreColor(ontology.avg_semantic_validity)}
      />
      <MetricCard
        label="Connectivity"
        value={`${ontology.connectivity.toFixed(0)}%`}
        description="Classes with inter-class relationships"
        colorClass={scoreColor(ontology.connectivity / 100)}
      />
      <MetricCard
        label="Structural Integrity"
        value={structuralIntegrity.toFixed(2)}
        description="Cycles + orphan penalty"
        colorClass={scoreColor(structuralIntegrity)}
      />
      <MetricCard
        label="Isolated Classes"
        value={String(islandCount)}
        description="Classes connected to nothing"
        colorClass={islandCount === 0 ? "text-green-600" : "text-red-600"}
      />
      <MetricCard
        label="Estimated Cost"
        value={ontology.estimated_cost !== null ? `$${ontology.estimated_cost.toFixed(4)}` : "N/A"}
        description="Extraction run cost"
        colorClass="text-gray-700"
      />
    </div>
  );
}
