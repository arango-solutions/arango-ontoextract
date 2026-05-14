"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, api } from "@/lib/api-client";
import {
  loadQualityHistory,
  type QualityHistorySnapshot,
} from "@/lib/qualityHistory";
import {
  PER_ONTOLOGY_QUALITY_DIMENSIONS,
  healthBgColor,
  healthColor,
  scoreBgColor,
  scoreColor,
  type PerOntologyQualityApiShape,
} from "@/lib/perOntologyQualityDimensions";

interface Props {
  name: string;
  data: PerOntologyQualityApiShape;
  onClose: () => void;
  /**
   * Optional click-through to the Revisions Inbox overlay (IBR.14).
   * When provided, the "Pending revisions" tile in the new
   * ``RevisionsActivitySection`` becomes a CTA that opens the inbox
   * for this ontology. Per ``ui-architecture.mdc`` rule 9 we never
   * navigate to a new route for this; the parent owns overlay state.
   */
  onShowInbox?: (ontologyId: string, ontologyName: string) => void;
}

interface RadarDatum {
  dimension: string;
  value: number;
  available: boolean;
}

const SCHEMA_METRIC_LABELS: Record<string, string> = {
  relationship_richness: "Relationship Richness",
  attribute_richness: "Attribute Richness",
  inheritance_richness: "Inheritance Richness",
  max_depth: "Max Depth",
  annotation_completeness: "Annotation Completeness",
  relationship_diversity: "Relationship Types",
  avg_connectivity_degree: "Avg Degree",
  uri_consistency: "URI Consistency",
};

function formatSchemaValue(key: string, v: number): string {
  if (
    key === "relationship_richness" ||
    key === "annotation_completeness" ||
    key === "uri_consistency"
  )
    return `${(v * 100).toFixed(0)}%`;
  if (key === "max_depth") return `${Math.round(v)} levels`;
  if (key === "attribute_richness") return `${v.toFixed(1)} props/class`;
  if (key === "inheritance_richness") return `${v.toFixed(1)} sub/parent`;
  if (key === "relationship_diversity") return `${v} distinct`;
  if (key === "avg_connectivity_degree") return `${v.toFixed(1)} edges/class`;
  return v.toFixed(4);
}

export default function QualityReportOverlay({
  name,
  data,
  onClose,
  onShowInbox,
}: Props) {
  const [schemaExpanded, setSchemaExpanded] = useState(false);
  const [history, setHistory] = useState<QualityHistorySnapshot[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const ontologyId = data.ontology_id;

  const loadHistory = useCallback(async () => {
    if (!ontologyId) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await loadQualityHistory(ontologyId, { limit: 30 });
      setHistory(res.snapshots);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Failed to load quality history");
    } finally {
      setHistoryLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const radarData: RadarDatum[] = PER_ONTOLOGY_QUALITY_DIMENSIONS.map(
    (dim) => {
      const raw = dim.compute(data);
      return {
        dimension: dim.label,
        value: raw != null ? Math.round(raw * 100) / 100 : 0,
        available: raw != null,
      };
    },
  );

  const schema = data.schema_metrics;
  const trendData = useMemo(
    () => history.map((snapshot, index) => ({
      label: formatSnapshotLabel(snapshot.timestamp, index),
      health: snapshot.health_score ?? null,
      completeness: snapshot.completeness ?? null,
      acceptance:
        snapshot.acceptance_rate != null
          ? Math.round(snapshot.acceptance_rate * 1000) / 10
          : null,
    })),
    [history],
  );

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative bg-white rounded-2xl shadow-2xl w-[90vw] max-w-[900px] max-h-[90vh] overflow-y-auto p-8">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close"
        >
          ×
        </button>

        <div className="space-y-8">
          {data.health_score != null && (
            <div className="flex justify-center">
              <div
                className={`rounded-2xl border-2 px-10 py-6 text-center shadow-sm ${healthBgColor(data.health_score)}`}
              >
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Health Score — {name}
                </p>
                <p
                  className={`mt-2 text-5xl font-extrabold ${healthColor(data.health_score)}`}
                >
                  {data.health_score}
                </p>
                <p className="text-sm text-gray-500 mt-1">out of 100</p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex items-center justify-center">
              <ResponsiveContainer width="100%" height={380}>
                <RadarChart
                  data={radarData}
                  cx="50%"
                  cy="50%"
                  outerRadius="70%"
                >
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 content-start">
              {PER_ONTOLOGY_QUALITY_DIMENSIONS.map((dim) => {
                const raw = dim.compute(data);
                const available = raw != null;
                const score = raw ?? 0;
                return (
                  <div
                    key={dim.key}
                    className={`rounded-xl border p-4 shadow-sm ${
                      available
                        ? scoreBgColor(score)
                        : "bg-gray-50 border-gray-200"
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
                      <span className="text-sm font-normal text-gray-400">
                        / 5
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-gray-500 leading-snug">
                      {available ? dim.description : "Data not available"}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {schema != null &&
            typeof schema === "object" &&
            Object.keys(schema).length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                <button
                  type="button"
                  onClick={() => setSchemaExpanded((p) => !p)}
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
                        <div
                          key={key}
                          className="bg-gray-50 rounded-lg border border-gray-100 p-3"
                        >
                          <p className="text-[11px] text-gray-500">
                            {SCHEMA_METRIC_LABELS[key] ??
                              key.replace(/_/g, " ")}
                          </p>
                          <p className="mt-1 text-sm font-semibold text-gray-800">
                            {typeof val === "number"
                              ? formatSchemaValue(key, val)
                              : String(val)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

          <RevisionsActivitySection
            ontologyId={ontologyId}
            ontologyName={name}
            onShowInbox={onShowInbox}
          />

          <QualityHistorySection
            loading={historyLoading}
            error={historyError}
            snapshots={history}
            trendData={trendData}
          />
        </div>
      </div>
    </div>
  );
}

function formatSnapshotLabel(timestamp: string | undefined, index: number): string {
  if (!timestamp) return `#${index + 1}`;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return `#${index + 1}`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatPct(v: number | null | undefined, scale: "ratio" | "percent" = "percent"): string {
  if (v == null) return "—";
  return `${(scale === "ratio" ? v * 100 : v).toFixed(1)}%`;
}

function QualityHistorySection({
  loading,
  error,
  snapshots,
  trendData,
}: {
  loading: boolean;
  error: string | null;
  snapshots: QualityHistorySnapshot[];
  trendData: { label: string; health: number | null; completeness: number | null; acceptance: number | null }[];
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">Quality History</h3>
          <p className="mt-1 text-xs text-gray-500">
            Timestamped snapshots from the quality API, useful for tracking trend after extraction,
            curation, and prompt changes.
          </p>
        </div>
        <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">
          {snapshots.length} snapshots
        </span>
      </div>

      {loading && (
        <p className="mt-4 text-sm text-gray-500">Loading quality history…</p>
      )}
      {error && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
          {error}
        </p>
      )}
      {!loading && !error && snapshots.length === 0 && (
        <p className="mt-4 text-sm text-gray-500">
          No historical snapshots yet. Opening this quality report records the first snapshot.
        </p>
      )}
      {!loading && !error && snapshots.length > 0 && (
        <div className="mt-5 grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#6b7280" }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#6b7280" }} />
                <Tooltip formatter={(value) => `${Number(value).toFixed(1)}%`} />
                <Line
                  type="monotone"
                  dataKey="health"
                  name="Health"
                  stroke="#2563eb"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="completeness"
                  name="Completeness"
                  stroke="#16a34a"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="acceptance"
                  name="Acceptance"
                  stroke="#9333ea"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="space-y-2">
            {snapshots.slice(-5).reverse().map((snapshot) => (
              <div
                key={snapshot._key ?? snapshot.timestamp}
                className="rounded-lg border border-gray-100 bg-gray-50 p-3"
              >
                <p className="text-[11px] font-medium text-gray-500">
                  {new Date(snapshot.timestamp).toLocaleString()}
                </p>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <Metric label="Health" value={snapshot.health_score?.toFixed(0) ?? "—"} />
                  <Metric label="Complete" value={formatPct(snapshot.completeness)} />
                  <Metric label="Accept" value={formatPct(snapshot.acceptance_rate, "ratio")} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-gray-400">{label}</p>
      <p className="font-semibold text-gray-800">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IBR.19 — Revisions activity tile
// ---------------------------------------------------------------------------
//
// Aggregates the most recent ``revision_meta`` rows for the current ontology
// into four small KPI tiles + a verdict-distribution row. We aggregate
// client-side from the existing ``GET /api/v1/revisions/?ontology_id=…``
// endpoint to avoid adding a backend stats endpoint just for the dashboard
// (we can promote it to a real stats endpoint when the inbox grows past a
// few hundred rows).

interface RevisionMetaSummary {
  _key: string;
  verdict: string;
  action: string;
  status: string;
  agent_type: string;
  created: number;
}

interface RevisionsListResponse {
  data: RevisionMetaSummary[];
  count: number;
}

interface RevisionStats {
  total: number;
  pending: number;
  applied: number;
  rejected: number;
  verdictCounts: Record<string, number>;
  topAgent: string | null;
  windowSize: number;
}

const VERDICT_BADGE: Record<string, string> = {
  REINFORCED: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  REFINED: "bg-amber-50 text-amber-700 border border-amber-200",
  "GAP-FILLING": "bg-indigo-50 text-indigo-700 border border-indigo-200",
  REDUNDANT: "bg-slate-100 text-slate-600 border border-slate-200",
  CONTRADICTED: "bg-rose-50 text-rose-700 border border-rose-200",
  UNCERTAIN: "bg-yellow-50 text-yellow-800 border border-yellow-200",
};

function aggregateRevisions(rows: RevisionMetaSummary[]): RevisionStats {
  const verdictCounts: Record<string, number> = {};
  const agentCounts: Record<string, number> = {};
  let pending = 0;
  let applied = 0;
  let rejected = 0;
  for (const r of rows) {
    verdictCounts[r.verdict] = (verdictCounts[r.verdict] ?? 0) + 1;
    if (r.agent_type) {
      agentCounts[r.agent_type] = (agentCounts[r.agent_type] ?? 0) + 1;
    }
    const status = (r.status || "").toLowerCase();
    if (status === "pending") pending += 1;
    else if (status === "rejected") rejected += 1;
    else if (status === "applied" || status === "accepted" || status === "modified")
      applied += 1;
  }
  let topAgent: string | null = null;
  let topAgentCount = -1;
  for (const [agent, count] of Object.entries(agentCounts)) {
    if (count > topAgentCount) {
      topAgent = agent;
      topAgentCount = count;
    }
  }
  return {
    total: rows.length,
    pending,
    applied,
    rejected,
    verdictCounts,
    topAgent,
    windowSize: rows.length,
  };
}

function RevisionsActivitySection({
  ontologyId,
  ontologyName,
  onShowInbox,
}: {
  ontologyId: string | undefined;
  ontologyName: string;
  onShowInbox?: (ontologyId: string, ontologyName: string) => void;
}) {
  const [stats, setStats] = useState<RevisionStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ontologyId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await api.get<RevisionsListResponse>(
          `/api/v1/revisions/?ontology_id=${encodeURIComponent(ontologyId)}&limit=200`,
        );
        if (cancelled) return;
        setStats(aggregateRevisions(res.data ?? []));
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to load revisions";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  if (!ontologyId) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">
            Revisions Activity
          </h3>
          <p className="mt-1 text-xs text-gray-500">
            Belief-revision audit trail — most recent {stats?.windowSize ?? 0}{" "}
            decisions for this ontology.
          </p>
        </div>
        {stats && stats.pending > 0 && onShowInbox && (
          <button
            type="button"
            onClick={() => onShowInbox(ontologyId, ontologyName)}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            Show inbox →
          </button>
        )}
      </div>

      {loading && (
        <p className="mt-4 text-sm text-gray-500">Loading revisions…</p>
      )}
      {error && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
          {error}
        </p>
      )}
      {!loading && !error && stats && stats.total === 0 && (
        <p className="mt-4 text-sm text-gray-500">
          No belief-revision activity recorded yet for this ontology.
        </p>
      )}
      {!loading && !error && stats && stats.total > 0 && (
        <div className="mt-5 space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <RevisionTile label="Total" value={stats.total} tone="neutral" />
            <RevisionTile
              label="Pending"
              value={stats.pending}
              tone={stats.pending > 0 ? "warning" : "neutral"}
              cta={
                stats.pending > 0 && onShowInbox
                  ? () => onShowInbox(ontologyId, ontologyName)
                  : undefined
              }
            />
            <RevisionTile label="Applied" value={stats.applied} tone="success" />
            <RevisionTile label="Rejected" value={stats.rejected} tone="muted" />
          </div>

          {Object.keys(stats.verdictCounts).length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-2">
                Verdict distribution
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.verdictCounts)
                  .sort((a, b) => b[1] - a[1])
                  .map(([verdict, count]) => (
                    <span
                      key={verdict}
                      className={`text-[11px] px-2 py-1 rounded-md font-medium ${
                        VERDICT_BADGE[verdict] ??
                        "bg-slate-50 text-slate-700 border border-slate-200"
                      }`}
                    >
                      {verdict} · {count}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {stats.topAgent && (
            <p className="text-[11px] text-gray-500">
              Top agent in window: <strong>{stats.topAgent}</strong>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function RevisionTile({
  label,
  value,
  tone,
  cta,
}: {
  label: string;
  value: number;
  tone: "neutral" | "success" | "warning" | "muted";
  cta?: () => void;
}) {
  const tones: Record<string, string> = {
    neutral: "bg-gray-50 border-gray-200 text-gray-800",
    success: "bg-emerald-50 border-emerald-200 text-emerald-800",
    warning: "bg-amber-50 border-amber-200 text-amber-800",
    muted: "bg-rose-50 border-rose-200 text-rose-800",
  };
  const baseClasses = `rounded-lg border p-3 ${tones[tone]} ${
    cta ? "cursor-pointer hover:opacity-90" : ""
  }`;
  const inner = (
    <>
      <p className="text-[11px] uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </>
  );
  if (cta) {
    return (
      <button type="button" onClick={cta} className={`${baseClasses} text-left`}>
        {inner}
      </button>
    );
  }
  return <div className={baseClasses}>{inner}</div>;
}
