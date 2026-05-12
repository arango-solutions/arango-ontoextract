"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import type { BeliefRevisionSummary, RunCostResponse } from "@/types/pipeline";

/**
 * Map IBR `reason` codes to human copy. Unknown reasons fall through
 * to the raw code so we never silently drop info; if a new reason
 * lands without a mapping the user still sees *something* that links
 * back to the backend symbol they can search for.
 */
const IBR_REASON_LABELS: Record<string, string> = {
  feature_flag_off: "IBR disabled in this environment",
  no_extraction_results: "No extraction results to revise",
  no_ontology_id: "No target ontology resolved",
  no_document_id: "No document context available",
};

function ibrReasonLabel(reason: string | undefined): string {
  if (!reason) return "Skipped";
  return IBR_REASON_LABELS[reason] ?? `Skipped: ${reason}`;
}

/**
 * Compose the Verdicts sublabel: a compact "AUTO_MERGE 3 · FLAG 2"
 * style string. Order is verdict-frequency descending so the most
 * common verdict reads first. Empty verdict_counts yields "—".
 */
function verdictsSublabel(counts: Record<string, number>): string {
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  if (entries.length === 0) return "—";
  entries.sort((a, b) => b[1] - a[1]);
  return entries
    .map(([verdict, n]) => `${verdict.replace(/^FLAG_FOR_/, "FLAG·")} ${n}`)
    .join(" · ");
}

interface RunMetricsProps {
  runId: string | null;
}

function formatDuration(ms: number | undefined): string {
  if (ms == null || ms === 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSec = seconds % 60;
  return `${minutes}m ${remainingSec}s`;
}

function formatNumber(n: number | undefined): string {
  if (n == null) return "0";
  return n.toLocaleString();
}

function formatCost(cost: number | undefined): string {
  if (cost == null) return "$0.00";
  return `$${cost.toFixed(2)}`;
}

function formatPercent(rate: number | undefined): string {
  if (rate == null) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
}

function MetricCard({ label, value, sublabel }: MetricCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        {label}
      </div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      {sublabel && (
        <div className="text-xs text-gray-400 mt-1">{sublabel}</div>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm animate-pulse">
      <div className="h-3 w-20 bg-gray-200 rounded mb-3" />
      <div className="h-7 w-16 bg-gray-200 rounded" />
    </div>
  );
}

export default function RunMetrics({ runId }: RunMetricsProps) {
  const [metrics, setMetrics] = useState<RunCostResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      setMetrics(null);
      return;
    }

    let cancelled = false;
    async function fetchMetrics() {
      setLoading(true);
      setError(null);
      try {
        const data = await api.get<RunCostResponse>(
          `/api/v1/extraction/runs/${runId}/cost`,
        );
        if (!cancelled) setMetrics(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load metrics");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchMetrics();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (!runId) {
    return (
      <div className="text-sm text-gray-400 p-4" data-testid="metrics-empty">
        Select a run to view metrics.
      </div>
    );
  }

  // Error must win over the no-metrics loading fallback, otherwise a failed
  // first fetch leaves users staring at perpetual skeletons.
  if (error) {
    return (
      <div className="text-sm text-red-500 p-4" data-testid="metrics-error">
        {error}
      </div>
    );
  }

  if (loading || !metrics) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 p-4" data-testid="metrics-loading">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  const confidenceLabel =
    metrics.avg_confidence != null
      ? `${(metrics.avg_confidence * 100).toFixed(1)}%`
      : "—";

  const confidenceSublabel =
    metrics.avg_confidence != null
      ? metrics.avg_confidence > 0.7
        ? "High confidence"
        : metrics.avg_confidence >= 0.5
          ? "Moderate confidence"
          : "Low confidence"
      : undefined;

  return (
    <div
      className="grid grid-cols-2 lg:grid-cols-5 gap-3 p-4"
      data-testid="run-metrics"
    >
      <MetricCard
        label="Total Duration"
        value={formatDuration(metrics.total_duration_ms)}
      />
      <MetricCard
        label="Token Usage"
        value={formatNumber(metrics.total_tokens)}
        sublabel={`${formatNumber(metrics.prompt_tokens)} prompt + ${formatNumber(metrics.completion_tokens)} completion`}
      />
      <MetricCard
        label="Estimated Cost"
        value={formatCost(metrics.estimated_cost)}
      />
      <MetricCard
        label="Entity Counts"
        value={String(
          (metrics.classes_extracted ?? 0) + (metrics.properties_extracted ?? 0),
        )}
        sublabel={`${metrics.classes_extracted ?? 0} classes + ${metrics.properties_extracted ?? 0} properties`}
      />
      <MetricCard
        label="Agreement Rate"
        value={formatPercent(metrics.pass_agreement_rate)}
        sublabel="Cross-pass consistency"
      />
      <MetricCard
        label="Avg Confidence"
        value={confidenceLabel}
        sublabel={confidenceSublabel}
      />
      <MetricCard
        label="Completeness"
        value={
          metrics.completeness_pct != null
            ? `${metrics.completeness_pct.toFixed(1)}%`
            : "—"
        }
        sublabel="Classes with properties"
      />
      <BeliefRevisionTiles ibr={metrics.belief_revision ?? null} />
    </div>
  );
}

/**
 * IBR.12 -- Pipeline Monitor tiles for the belief-revision phase.
 *
 * Three states:
 *   1. `ibr === null`            -- legacy run with no IBR data; one
 *                                   neutral "—" tile so the row stays
 *                                   even-width but the user knows
 *                                   there's no signal here.
 *   2. `status === "skipped"`    -- IBR didn't run; one tile shows
 *                                   the human-readable reason so the
 *                                   user knows it isn't a missing
 *                                   metric, it's a deliberate no-op.
 *   3. `status` is "completed"   -- four tiles: Touchpoints,
 *      / "failed"                  Verdicts (with breakdown sublabel),
 *                                   Auto-applied, Flagged for
 *                                   curation. LLM invocations is
 *                                   folded into the Verdicts sublabel
 *                                   to keep the row visually balanced
 *                                   instead of growing a 9th column.
 */
function BeliefRevisionTiles({
  ibr,
}: {
  ibr: BeliefRevisionSummary | null;
}) {
  if (ibr == null) {
    return (
      <MetricCard
        label="Belief Revision"
        value="—"
        sublabel="No IBR data on this run"
      />
    );
  }

  if (ibr.status === "skipped") {
    return (
      <MetricCard
        label="Belief Revision"
        value="Skipped"
        sublabel={ibrReasonLabel(ibr.reason)}
      />
    );
  }

  // status === "completed" or "failed" -- show the real numbers.
  const statusSuffix = ibr.status === "failed" ? " (failed)" : "";
  return (
    <>
      <MetricCard
        label={`IBR Touchpoints${statusSuffix}`}
        value={formatNumber(ibr.touchpoints_discovered)}
        sublabel={`${ibr.llm_invocations} LLM call${ibr.llm_invocations === 1 ? "" : "s"}`}
      />
      <MetricCard
        label="IBR Verdicts"
        value={formatNumber(
          Object.values(ibr.verdict_counts).reduce((a, b) => a + b, 0),
        )}
        sublabel={verdictsSublabel(ibr.verdict_counts)}
      />
      <MetricCard
        label="IBR Auto-applied"
        value={formatNumber(ibr.auto_applied)}
        sublabel={
          ibr.skipped_idempotency > 0
            ? `${ibr.skipped_idempotency} skipped (idempotent)`
            : undefined
        }
      />
      <MetricCard
        label="IBR Flagged for Curation"
        value={formatNumber(ibr.flagged_for_curation)}
        sublabel={
          ibr.flagged_for_curation > 0
            ? "Awaiting human review"
            : "Nothing pending"
        }
      />
    </>
  );
}
