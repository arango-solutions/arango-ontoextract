"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { api, type PaginatedResponse } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  health_score: number | null;
  acceptance_rate: number | null;
  schema_metrics?: SchemaMetrics;
}

interface QualitySummary {
  ontology_count: number;
  total_classes: number;
  total_properties: number;
  avg_confidence: number | null;
  avg_completeness: number;
  ontologies_with_cycles: number;
  total_orphans: number;
}

interface OntologyEntry {
  _key: string;
  name: string;
  description: string;
  class_count: number;
}

// ---------------------------------------------------------------------------
// Dimension descriptors
// ---------------------------------------------------------------------------

interface DimensionDescriptor {
  key: string;
  label: string;
  description: string;
  compute: (q: QualityData) => number | null;
}

const DIMENSIONS: DimensionDescriptor[] = [
  {
    key: "annotation",
    label: "Annotation Quality",
    description: "Completeness of labels, descriptions, and comments on classes/properties",
    compute: (q) =>
      q.schema_metrics ? q.schema_metrics.annotation_completeness * 5 : null,
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
    description: "Average confidence score from multi-signal extraction judges",
    compute: (q) => (q.avg_confidence != null ? q.avg_confidence * 5 : null),
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number): string {
  if (score >= 3.5) return "text-green-600";
  if (score >= 2.0) return "text-yellow-600";
  return "text-red-600";
}

function scoreBgColor(score: number): string {
  if (score >= 3.5) return "bg-green-50 border-green-200";
  if (score >= 2.0) return "bg-yellow-50 border-yellow-200";
  return "bg-red-50 border-red-200";
}

function healthColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-yellow-600";
  return "text-red-600";
}

function healthBgColor(score: number): string {
  if (score >= 70) return "bg-green-50 border-green-300";
  if (score >= 40) return "bg-yellow-50 border-yellow-300";
  return "bg-red-50 border-red-300";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const ALL_ONTOLOGIES_KEY = "__all__";

export default function QualityDashboard() {
  const [ontologies, setOntologies] = useState<OntologyEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string>(ALL_ONTOLOGIES_KEY);
  const [qualityData, setQualityData] = useState<QualityData | null>(null);
  const [summary, setSummary] = useState<QualitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [schemaExpanded, setSchemaExpanded] = useState(false);

  // Load ontology list on mount
  useEffect(() => {
    api
      .get<PaginatedResponse<OntologyEntry>>("/api/v1/ontology/library?limit=100")
      .then((res) => {
        setOntologies(res.data ?? []);
        if (res.data?.length) {
          setSelectedId(res.data[0]._key);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load ontologies");
      });
  }, []);

  const fetchQuality = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    setQualityData(null);
    setSummary(null);

    try {
      if (id === ALL_ONTOLOGIES_KEY) {
        const res = await api.get<QualitySummary>("/api/v1/quality/summary");
        setSummary(res);
      } else {
        const res = await api.get<QualityData>(`/api/v1/quality/${id}`);
        setQualityData(res);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load quality data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchQuality(selectedId);
    }
  }, [selectedId, fetchQuality]);

  const isAggregate = selectedId === ALL_ONTOLOGIES_KEY;
  const selectedName =
    isAggregate
      ? "All Ontologies"
      : ontologies.find((o) => o._key === selectedId)?.name ?? selectedId;

  // Build radar data from per-ontology quality
  const radarData = qualityData
    ? DIMENSIONS.map((dim) => {
        const raw = dim.compute(qualityData);
        return {
          dimension: dim.label,
          value: raw != null ? Math.round(raw * 100) / 100 : 0,
          available: raw != null,
        };
      })
    : null;

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-8 flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Ontology Quality Dashboard
            </h1>
            <p className="mt-2 text-gray-500 text-lg">
              Multi-dimensional quality assessment for extracted ontologies
            </p>
          </div>
          <Link
            href="/"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium mt-1"
          >
            &larr; Home
          </Link>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {/* Ontology selector */}
        <div className="flex items-center gap-4">
          <label
            htmlFor="ontology-select"
            className="text-sm font-semibold text-gray-500 uppercase tracking-wide"
          >
            Ontology
          </label>
          <select
            id="ontology-select"
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            <option value={ALL_ONTOLOGIES_KEY}>All Ontologies (Aggregate)</option>
            {ontologies.map((o) => (
              <option key={o._key} value={o._key}>
                {o.name}
              </option>
            ))}
          </select>
        </div>

        {/* Error state */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700">
            <p className="font-semibold">Error loading quality data</p>
            <p className="text-sm mt-1">{error}</p>
          </div>
        )}

        {/* Loading state */}
        {loading && !error && (
          <div className="flex items-center justify-center py-20">
            <div className="text-center space-y-3">
              <div className="h-10 w-10 mx-auto border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
              <p className="text-gray-500 text-sm">Loading quality metrics…</p>
            </div>
          </div>
        )}

        {/* Aggregate summary view */}
        {!loading && !error && isAggregate && summary && (
          <AggregateView summary={summary} />
        )}

        {/* Per-ontology detailed view */}
        {!loading && !error && !isAggregate && qualityData && radarData && (
          <OntologyDetailView
            name={selectedName}
            data={qualityData}
            radarData={radarData}
            schemaExpanded={schemaExpanded}
            onToggleSchema={() => setSchemaExpanded((p) => !p)}
          />
        )}

        {/* Empty state */}
        {!loading && !error && !qualityData && !summary && (
          <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
            <p className="text-gray-400 text-lg">No quality data available.</p>
            <p className="text-gray-400 text-sm mt-1">
              Extract an ontology first, then come back here.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Aggregate summary view
// ---------------------------------------------------------------------------

function AggregateView({ summary }: { summary: QualitySummary }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Ontologies" value={summary.ontology_count} />
        <StatCard label="Total Classes" value={summary.total_classes} />
        <StatCard label="Total Properties" value={summary.total_properties} />
        <StatCard
          label="Avg Confidence"
          value={
            summary.avg_confidence != null
              ? `${(summary.avg_confidence * 100).toFixed(1)}%`
              : "—"
          }
        />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <StatCard
          label="Avg Completeness"
          value={`${summary.avg_completeness.toFixed(1)}%`}
        />
        <StatCard
          label="Ontologies with Cycles"
          value={summary.ontologies_with_cycles}
          warn={summary.ontologies_with_cycles > 0}
        />
        <StatCard
          label="Total Orphans"
          value={summary.total_orphans}
          warn={summary.total_orphans > 0}
        />
      </div>
      <p className="text-sm text-gray-400">
        Select a specific ontology from the dropdown to see the full radar chart
        and dimensional breakdown.
      </p>
    </div>
  );
}

function StatCard({
  label,
  value,
  warn,
}: {
  label: string;
  value: string | number;
  warn?: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </p>
      <p
        className={`mt-2 text-2xl font-bold ${warn ? "text-yellow-600" : "text-gray-900"}`}
      >
        {value}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-ontology detail view
// ---------------------------------------------------------------------------

interface RadarDatum {
  dimension: string;
  value: number;
  available: boolean;
}

function OntologyDetailView({
  name,
  data,
  radarData,
  schemaExpanded,
  onToggleSchema,
}: {
  name: string;
  data: QualityData;
  radarData: RadarDatum[];
  schemaExpanded: boolean;
  onToggleSchema: () => void;
}) {
  return (
    <div className="space-y-8">
      {/* Health score */}
      {data.health_score != null && (
        <div className="flex justify-center">
          <div
            className={`rounded-2xl border-2 px-10 py-6 text-center shadow-sm ${healthBgColor(data.health_score)}`}
          >
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Health Score — {name}
            </p>
            <p className={`mt-2 text-5xl font-extrabold ${healthColor(data.health_score)}`}>
              {data.health_score}
            </p>
            <p className="text-sm text-gray-500 mt-1">out of 100</p>
          </div>
        </div>
      )}

      {/* Radar + score cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Radar chart */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex items-center justify-center">
          <ResponsiveContainer width="100%" height={420}>
            <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="70%">
              <PolarGrid stroke="#e5e7eb" />
              <PolarAngleAxis
                dataKey="dimension"
                tick={{ fontSize: 12, fill: "#4b5563" }}
              />
              <PolarRadiusAxis
                angle={90}
                domain={[0, 5]}
                tickCount={6}
                tick={{ fontSize: 10, fill: "#9ca3af" }}
              />
              <Radar
                name="Quality"
                dataKey="value"
                stroke="#2563eb"
                fill="#3b82f6"
                fillOpacity={0.3}
                strokeWidth={2}
              />
              <Tooltip
                formatter={(val) => `${Number(val).toFixed(2)} / 5`}
                labelStyle={{ fontWeight: 600 }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {/* Score cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {DIMENSIONS.map((dim) => {
            const raw = dim.compute(data);
            const available = raw != null;
            const score = raw ?? 0;
            return (
              <div
                key={dim.key}
                className={`rounded-xl border p-4 shadow-sm ${
                  available ? scoreBgColor(score) : "bg-gray-50 border-gray-200"
                }`}
              >
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  {dim.label}
                </p>
                <p
                  className={`mt-1 text-2xl font-bold ${
                    available ? scoreColor(score) : "text-gray-300"
                  }`}
                >
                  {available ? score.toFixed(1) : "—"}{" "}
                  <span className="text-sm font-normal text-gray-400">/ 5</span>
                </p>
                <p className="mt-1 text-xs text-gray-500 leading-snug">
                  {available ? dim.description : "Data not available"}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Schema metrics (OntoQA) */}
      {data.schema_metrics && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
          <button
            type="button"
            onClick={onToggleSchema}
            className="w-full flex items-center justify-between px-6 py-4 text-left"
          >
            <h3 className="text-sm font-semibold text-gray-700">
              OntoQA Schema Metrics
            </h3>
            <span className="text-gray-400 text-lg">
              {schemaExpanded ? "−" : "+"}
            </span>
          </button>
          {schemaExpanded && (
            <div className="px-6 pb-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                <SchemaMetricCard
                  label="Relationship Richness"
                  value={`${(data.schema_metrics.relationship_richness * 100).toFixed(0)}%`}
                />
                <SchemaMetricCard
                  label="Attribute Richness"
                  value={`${data.schema_metrics.attribute_richness.toFixed(1)} props/class`}
                />
                <SchemaMetricCard
                  label="Inheritance Richness"
                  value={`${data.schema_metrics.inheritance_richness.toFixed(1)} sub/parent`}
                />
                <SchemaMetricCard
                  label="Max Depth"
                  value={`${data.schema_metrics.max_depth} levels`}
                />
                <SchemaMetricCard
                  label="Annotation Completeness"
                  value={`${(data.schema_metrics.annotation_completeness * 100).toFixed(0)}%`}
                />
                <SchemaMetricCard
                  label="Relationship Types"
                  value={`${data.schema_metrics.relationship_diversity} distinct`}
                />
                <SchemaMetricCard
                  label="Avg Degree"
                  value={`${data.schema_metrics.avg_connectivity_degree.toFixed(1)} edges/class`}
                />
                <SchemaMetricCard
                  label="URI Consistency"
                  value={`${(data.schema_metrics.uri_consistency * 100).toFixed(0)}%`}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SchemaMetricCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="bg-gray-50 rounded-lg border border-gray-100 p-3">
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-gray-800">{value}</p>
    </div>
  );
}
