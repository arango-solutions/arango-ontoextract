"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

interface SchemaMetrics {
  relationship_richness: number;
  attribute_richness: number;
  inheritance_richness: number;
  max_depth: number;
  annotation_completeness: number;
  relationship_diversity: number;
  avg_connectivity_degree: number;
  uri_consistency: number;
}

interface QualityData {
  avg_confidence: number | null;
  class_count: number;
  property_count: number;
  completeness: number;
  connectivity: number;
  relationship_count: number;
  orphan_count: number;
  has_cycles: boolean;
  classes_without_properties: number;
  acceptance_rate: number | null;
  time_to_ontology_ms: number | null;
  schema_metrics?: SchemaMetrics;
}

function confidenceColorClass(value: number): string {
  if (value > 0.7) return "text-green-600";
  if (value >= 0.5) return "text-yellow-600";
  return "text-red-600";
}

function confidenceBgClass(value: number): string {
  if (value > 0.7) return "bg-green-100 text-green-700";
  if (value >= 0.5) return "bg-yellow-100 text-yellow-700";
  return "bg-red-100 text-red-700";
}

interface QualityPanelProps {
  ontologyId: string;
}

export default function QualityPanel({ ontologyId }: QualityPanelProps) {
  const [data, setData] = useState<QualityData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchQuality() {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get<QualityData>(
          `/api/v1/quality/${ontologyId}`,
        );
        if (!cancelled) setData(res);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load quality data",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchQuality();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  if (loading) {
    return (
      <div
        className="border-t border-gray-100 pt-3 mt-3"
        data-testid="quality-loading"
      >
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Quality
        </div>
        <div className="animate-pulse space-y-2">
          <div className="h-3 w-24 bg-gray-200 rounded" />
          <div className="h-3 w-32 bg-gray-200 rounded" />
        </div>
      </div>
    );
  }

  if (error || !data) return null;

  const hasIssues = data.orphan_count > 0 || data.has_cycles || data.connectivity === 0;

  return (
    <div
      className="border-t border-gray-100 pt-3 mt-3"
      data-testid="quality-panel"
    >
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Quality
      </div>
      <div className="space-y-1.5 text-xs">
        {/* Average Confidence */}
        {data.avg_confidence != null && (
          <div className="flex items-center justify-between">
            <span className="text-gray-600">Avg Confidence</span>
            <span
              className={`font-semibold px-1.5 py-0.5 rounded ${confidenceBgClass(data.avg_confidence)}`}
            >
              {(data.avg_confidence * 100).toFixed(1)}%
            </span>
          </div>
        )}

        {/* Completeness */}
        <div className="flex items-center justify-between">
          <span className="text-gray-600">Completeness</span>
          <span className="text-gray-800 font-medium">
            {data.completeness.toFixed(1)}%
          </span>
        </div>

        {/* Connectivity */}
        <div className="flex items-center justify-between">
          <span className="text-gray-600">Connectivity</span>
          <span className={`font-medium ${data.connectivity > 50 ? "text-green-700" : data.connectivity > 0 ? "text-yellow-700" : "text-red-600"}`}>
            {data.connectivity.toFixed(1)}%
            <span className="text-xs text-gray-400 ml-1">({data.relationship_count} relationships)</span>
          </span>
        </div>
        {data.connectivity === 0 && (
          <div className="text-xs text-red-500 bg-red-50 px-2 py-1 rounded">
            No inter-class relationships detected. The ontology is a flat taxonomy without object property connections between classes.
          </div>
        )}

        {/* Orphans */}
        {data.orphan_count > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-gray-600">Orphan Classes</span>
            <span className="font-semibold px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700">
              {data.orphan_count}
            </span>
          </div>
        )}

        {/* Cycles */}
        {data.has_cycles && (
          <div className="flex items-center justify-between">
            <span className="text-gray-600">Structural Issues</span>
            <span className="font-semibold px-1.5 py-0.5 rounded bg-red-100 text-red-700">
              Cycle detected
            </span>
          </div>
        )}

        {/* Acceptance rate */}
        {data.acceptance_rate != null && (
          <div className="flex items-center justify-between">
            <span className="text-gray-600">Acceptance Rate</span>
            <span
              className={`font-semibold ${confidenceColorClass(data.acceptance_rate)}`}
            >
              {(data.acceptance_rate * 100).toFixed(1)}%
            </span>
          </div>
        )}

        {!hasIssues && data.completeness >= 100 && data.connectivity > 0 && (
          <div className="text-green-600 text-[11px] mt-1">
            No structural issues detected.
          </div>
        )}

        {/* Schema Metrics (OntoQA-aligned) */}
        {data.schema_metrics && (
          <details className="mt-2">
            <summary className="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600">
              Schema Metrics (OntoQA)
            </summary>
            <div className="mt-1.5 space-y-1 text-[11px]">
              <div className="flex justify-between">
                <span className="text-gray-500">Relationship Richness</span>
                <span className="text-gray-700">{(data.schema_metrics.relationship_richness * 100).toFixed(0)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Attribute Richness</span>
                <span className="text-gray-700">{data.schema_metrics.attribute_richness.toFixed(1)} props/class</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Inheritance Richness</span>
                <span className="text-gray-700">{data.schema_metrics.inheritance_richness.toFixed(1)} subclasses/parent</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Max Depth</span>
                <span className="text-gray-700">{data.schema_metrics.max_depth} levels</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Annotation Completeness</span>
                <span className="text-gray-700">{(data.schema_metrics.annotation_completeness * 100).toFixed(0)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Relationship Types</span>
                <span className="text-gray-700">{data.schema_metrics.relationship_diversity} distinct</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Avg Degree</span>
                <span className="text-gray-700">{data.schema_metrics.avg_connectivity_degree.toFixed(1)} edges/class</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">URI Consistency</span>
                <span className="text-gray-700">{(data.schema_metrics.uri_consistency * 100).toFixed(0)}%</span>
              </div>
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
