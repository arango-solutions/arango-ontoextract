"use client";

import { useCallback, useEffect, useState } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type { QualityDashboard, QualitySummary } from "@/types/curation";
import {
  PER_ONTOLOGY_QUALITY_DIMENSIONS,
  healthBgColor,
  healthColor,
  scoreBgColor,
  scoreColor,
  type PerOntologyQualityApiShape,
} from "@/lib/perOntologyQualityDimensions";

const ALL_ONTOLOGIES_KEY = "__all__";
const DASHBOARD_FETCH_TIMEOUT_MS = 120_000;

interface OntologyEntry {
  _key: string;
  name: string;
  description?: string;
  class_count?: number;
}

interface RadarDatum {
  dimension: string;
  value: number;
  available: boolean;
}

function formatSchemaMetricLabel(key: string): string {
  const map: Record<string, string> = {
    relationship_richness: "Relationship Richness",
    attribute_richness: "Attribute Richness",
    inheritance_richness: "Inheritance Richness",
    max_depth: "Max Depth",
    annotation_completeness: "Annotation Completeness",
    relationship_diversity: "Relationship Types",
    avg_connectivity_degree: "Avg Degree",
    uri_consistency: "URI Consistency",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function formatSchemaMetricValue(key: string, v: number): string {
  if (key === "relationship_richness" || key === "annotation_completeness" || key === "uri_consistency") {
    return `${(v * 100).toFixed(0)}%`;
  }
  if (key === "max_depth") return `${Math.round(v)} levels`;
  if (key === "attribute_richness") return `${v.toFixed(1)} props/class`;
  if (key === "inheritance_richness") return `${v.toFixed(1)} sub/parent`;
  if (key === "relationship_diversity") return `${v} distinct`;
  if (key === "avg_connectivity_degree") return `${v.toFixed(1)} edges/class`;
  return v.toFixed(4);
}

/**
 * Live per-ontology quality view restored from commit b12189e (Apr 2026):
 * ontology picker, 0–5 radar over six dimensions, score cards, expandable schema metrics.
 * Aggregate row uses `/quality/dashboard` summary (replaces removed `/quality/summary`).
 */
export default function PerOntologyQualityReport() {
  const [ontologies, setOntologies] = useState<OntologyEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string>(ALL_ONTOLOGIES_KEY);
  const [ontologyListReady, setOntologyListReady] = useState(false);
  const [qualityData, setQualityData] = useState<PerOntologyQualityApiShape | null>(null);
  const [summary, setSummary] = useState<QualitySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [schemaExpanded, setSchemaExpanded] = useState(false);

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
        setError(
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to load ontologies",
        );
      })
      .finally(() => {
        setOntologyListReady(true);
      });
  }, []);

  const fetchQuality = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    setQualityData(null);
    setSummary(null);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), DASHBOARD_FETCH_TIMEOUT_MS);

    try {
      if (id === ALL_ONTOLOGIES_KEY) {
        const dash = await api.get<QualityDashboard>("/api/v1/quality/dashboard", {
          signal: controller.signal,
        });
        setSummary(dash.summary);
      } else {
        const res = await api.get<PerOntologyQualityApiShape>(`/api/v1/quality/${id}`, {
          signal: controller.signal,
        });
        setQualityData(res);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError(
          `Request timed out after ${DASHBOARD_FETCH_TIMEOUT_MS / 1000}s. Try a single ontology or retry.`,
        );
      } else if (err instanceof ApiError) {
        setError(err.body.message || `Request failed (${err.status})`);
      } else {
        setError(err instanceof Error ? err.message : "Failed to load quality data");
      }
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ontologyListReady) return;
    void fetchQuality(selectedId);
  }, [selectedId, fetchQuality, ontologyListReady]);

  const isAggregate = selectedId === ALL_ONTOLOGIES_KEY;
  const selectedName =
    isAggregate
      ? "All Ontologies"
      : ontologies.find((o) => o._key === selectedId)?.name ?? selectedId;

  const radarData: RadarDatum[] | null = qualityData
    ? PER_ONTOLOGY_QUALITY_DIMENSIONS.map((dim) => {
        const raw = dim.compute(qualityData);
        return {
          dimension: dim.label,
          value: raw != null ? Math.round(raw * 100) / 100 : 0,
          available: raw != null,
        };
      })
    : null;

  return (
    <div className="space-y-8">
      <p className="text-sm text-gray-600">
        Live metrics from the API for each ontology (same six dimensions and 0–5 radar as the
        original quality dashboard). &quot;All Ontologies&quot; loads aggregate summary from the
        quality dashboard endpoint.
      </p>

      <div className="flex flex-wrap items-center gap-4">
        <label
          htmlFor="per-ontology-quality-select"
          className="text-sm font-semibold text-gray-500 uppercase tracking-wide"
        >
          Ontology
        </label>
        <select
          id="per-ontology-quality-select"
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
        >
          <option value={ALL_ONTOLOGIES_KEY}>All Ontologies (aggregate)</option>
          {ontologies.map((o) => (
            <option key={o._key} value={o._key}>
              {o.name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700">
          <p className="font-semibold">Error loading quality data</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      )}

      {loading && !error && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center space-y-3">
            <div className="h-10 w-10 mx-auto border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
            <p className="text-gray-500 text-sm">Loading quality metrics…</p>
          </div>
        </div>
      )}

      {!loading && !error && isAggregate && summary && (
        <AggregateView summary={summary} />
      )}

      {!loading && !error && !isAggregate && qualityData && radarData && (
        <OntologyDetailView
          name={selectedName}
          data={qualityData}
          radarData={radarData}
          schemaExpanded={schemaExpanded}
          onToggleSchema={() => setSchemaExpanded((p) => !p)}
        />
      )}

      {!loading && !error && !qualityData && !summary && (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-400 text-lg">No quality data available.</p>
          <p className="text-gray-400 text-sm mt-1">
            Extract an ontology first, then open this tab again.
          </p>
        </div>
      )}
    </div>
  );
}

function AggregateView({ summary }: { summary: QualitySummary }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Ontologies" value={summary.ontology_count} />
        <StatCard label="Total Classes" value={summary.total_classes} />
        <StatCard label="Total Properties" value={summary.total_properties} />
        <StatCard
          label="Avg Health Score"
          value={
            summary.avg_health_score != null
              ? String(summary.avg_health_score)
              : "—"
          }
        />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <StatCard
          label="Avg Faithfulness (mean)"
          value={
            summary.avg_faithfulness != null
              ? `${(summary.avg_faithfulness * 100).toFixed(1)}%`
              : "—"
          }
        />
        <StatCard
          label="Avg Semantic Validity"
          value={
            summary.avg_semantic_validity != null
              ? `${(summary.avg_semantic_validity * 100).toFixed(1)}%`
              : "—"
          }
        />
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
        Select a specific ontology to see the six-dimension radar and per-dimension score cards.
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

function OntologyDetailView({
  name,
  data,
  radarData,
  schemaExpanded,
  onToggleSchema,
}: {
  name: string;
  data: PerOntologyQualityApiShape;
  radarData: RadarDatum[];
  schemaExpanded: boolean;
  onToggleSchema: () => void;
}) {
  const schema = data.schema_metrics;

  return (
    <div className="space-y-8">
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
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

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {PER_ONTOLOGY_QUALITY_DIMENSIONS.map((dim) => {
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

      {schema != null && typeof schema === "object" && Object.keys(schema).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
          <button
            type="button"
            onClick={onToggleSchema}
            className="w-full flex items-center justify-between px-6 py-4 text-left"
          >
            <h3 className="text-sm font-semibold text-gray-700">
              OntoQA / schema metrics
            </h3>
            <span className="text-gray-400 text-lg">
              {schemaExpanded ? "−" : "+"}
            </span>
          </button>
          {schemaExpanded && (
            <div className="px-6 pb-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(schema).map(([key, val]) => (
                  <div key={key} className="bg-gray-50 rounded-lg border border-gray-100 p-3">
                    <p className="text-[11px] text-gray-500">{formatSchemaMetricLabel(key)}</p>
                    <p className="mt-1 text-sm font-semibold text-gray-800">
                      {typeof val === "number" ? formatSchemaMetricValue(key, val) : String(val)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
