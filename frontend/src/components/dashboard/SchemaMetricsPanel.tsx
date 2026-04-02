"use client";

import { useState } from "react";
import type { SchemaMetrics } from "@/types/curation";

interface Props {
  schemaMetrics: SchemaMetrics | null;
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-lg border border-gray-100 p-3">
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-gray-800">{value}</p>
    </div>
  );
}

export default function SchemaMetricsPanel({ schemaMetrics }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!schemaMetrics) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left"
      >
        <h3 className="text-sm font-semibold text-gray-700">
          OntoQA Schema Metrics
        </h3>
        <span className="text-gray-400 text-lg">
          {expanded ? "\u2212" : "+"}
        </span>
      </button>
      {expanded && (
        <div className="px-5 pb-5">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricItem
              label="Relationship Richness"
              value={`${(schemaMetrics.relationship_richness * 100).toFixed(0)}%`}
            />
            <MetricItem
              label="Attribute Richness"
              value={`${schemaMetrics.attribute_richness.toFixed(1)} props/class`}
            />
            <MetricItem
              label="Inheritance Richness"
              value={`${schemaMetrics.inheritance_richness.toFixed(1)} sub/parent`}
            />
            <MetricItem
              label="Max Depth"
              value={`${schemaMetrics.max_depth} levels`}
            />
            <MetricItem
              label="Annotation Completeness"
              value={`${(schemaMetrics.annotation_completeness * 100).toFixed(0)}%`}
            />
            <MetricItem
              label="Relationship Types"
              value={`${schemaMetrics.relationship_diversity} distinct`}
            />
            <MetricItem
              label="Avg Degree"
              value={`${schemaMetrics.avg_connectivity_degree.toFixed(1)} edges/class`}
            />
            <MetricItem
              label="URI Consistency"
              value={`${(schemaMetrics.uri_consistency * 100).toFixed(0)}%`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
