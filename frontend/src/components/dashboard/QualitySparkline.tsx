"use client";

/**
 * Q.3 — Inline trend sparkline for the dashboard ontology table.
 *
 * Pulls the last N quality_history snapshots for one ontology and renders
 * a tiny inline SVG of one metric (default ``health_score``) so the
 * scorecard column conveys "is this getting better or worse" at a glance.
 *
 * Constraints driving the design:
 *
 * - Pure SVG, no recharts ``<ResponsiveContainer>`` per row. The
 *   dashboard can show 50+ ontologies; a recharts instance per row was
 *   measurably noisy in profiling.
 * - Lazy fetch on mount. The dashboard payload does not include history,
 *   and forcing it to would balloon the response. Each row makes one
 *   small ``GET /quality/{id}/history?limit=...`` and caches the result
 *   in a module-level ``Map`` so re-mounts (filter / sort) reuse the
 *   data without a refetch.
 * - Event-source styling. Snapshots tagged ``extraction_completion`` or
 *   ``promotion`` get a small dot accent so the eye finds the
 *   "something actually happened here" datapoints, vs ``quality_api``
 *   noise from someone repeatedly opening the report.
 * - Accessibility: numeric ``title`` (mouse) plus ``aria-label`` so a
 *   screen reader announces "Trend: 72 to 78, last 7 snapshots".
 */

import { useEffect, useState } from "react";
import {
  loadQualityHistory,
  type QualityHistorySnapshot,
} from "@/lib/qualityHistory";

// ---------------------------------------------------------------------------
// Module-level cache so re-mounts (sort, filter) don't refetch
// ---------------------------------------------------------------------------

const _historyCache = new Map<string, QualityHistorySnapshot[]>();
const _inflight = new Map<string, Promise<QualityHistorySnapshot[]>>();

async function fetchHistoryCached(
  ontologyId: string,
  limit: number,
): Promise<QualityHistorySnapshot[]> {
  const cached = _historyCache.get(ontologyId);
  if (cached) return cached;
  const inflight = _inflight.get(ontologyId);
  if (inflight) return inflight;

  const promise = loadQualityHistory(ontologyId, { limit })
    .then((res) => {
      const snapshots = res.snapshots ?? [];
      _historyCache.set(ontologyId, snapshots);
      return snapshots;
    })
    .finally(() => {
      _inflight.delete(ontologyId);
    });
  _inflight.set(ontologyId, promise);
  return promise;
}

/** Test-only — clear the cache between specs. */
export function _resetSparklineCacheForTests(): void {
  _historyCache.clear();
  _inflight.clear();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type MetricKey =
  | "health_score"
  | "completeness"
  | "acceptance_rate"
  | "avg_confidence";

const EVENT_SOURCES = new Set(["extraction_completion", "promotion"]);

function pickMetric(snap: QualityHistorySnapshot, key: MetricKey): number | null {
  const v = snap[key];
  if (v == null) return null;
  if (key === "acceptance_rate") return v * 100; // ratio → %
  return v;
}

function trendArrow(first: number | null, last: number | null): string {
  if (first == null || last == null) return "";
  if (last > first + 0.5) return "↑";
  if (last < first - 0.5) return "↓";
  return "→";
}

function trendColor(first: number | null, last: number | null): string {
  if (first == null || last == null) return "text-gray-400";
  if (last > first + 0.5) return "text-emerald-600";
  if (last < first - 0.5) return "text-rose-600";
  return "text-gray-500";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface QualitySparklineProps {
  ontologyId: string;
  /** Which metric to render. Defaults to ``health_score``. */
  metric?: MetricKey;
  /** SVG width in pixels. Defaults to 80. */
  width?: number;
  /** SVG height in pixels. Defaults to 24. */
  height?: number;
  /** Max snapshots to fetch. Defaults to 12. */
  limit?: number;
}

export default function QualitySparkline({
  ontologyId,
  metric = "health_score",
  width = 80,
  height = 24,
  limit = 12,
}: QualitySparklineProps) {
  const [snapshots, setSnapshots] = useState<QualityHistorySnapshot[] | null>(
    () => _historyCache.get(ontologyId) ?? null,
  );
  const [error, setError] = useState(false);

  useEffect(() => {
    if (snapshots != null) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await fetchHistoryCached(ontologyId, limit);
        if (!cancelled) setSnapshots(rows);
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId, limit, snapshots]);

  if (error) {
    return (
      <span className="text-[10px] text-gray-300" aria-label="Trend unavailable">
        —
      </span>
    );
  }

  if (snapshots == null) {
    return (
      <span
        className="inline-block bg-gray-100 rounded animate-pulse"
        style={{ width, height }}
        aria-label="Loading trend"
      />
    );
  }

  const points = snapshots
    .map((s) => ({
      value: pickMetric(s, metric),
      source: s.source ?? "quality_api",
    }))
    .filter((p): p is { value: number; source: string } => p.value != null);

  if (points.length === 0) {
    return (
      <span className="text-[10px] text-gray-300" aria-label="No trend data">
        —
      </span>
    );
  }

  if (points.length === 1) {
    // Single point — render a flat dot instead of a degenerate line.
    return (
      <span
        className="inline-flex items-center gap-1 text-[10px] text-gray-400"
        aria-label={`Trend: single snapshot at ${points[0].value.toFixed(0)}`}
      >
        <svg width={width} height={height} aria-hidden>
          <circle cx={width / 2} cy={height / 2} r={2.5} fill="#9ca3af" />
        </svg>
      </span>
    );
  }

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const stepX = points.length === 1 ? 0 : (width - 4) / (points.length - 1);

  const polylinePoints = points
    .map((p, i) => {
      const x = 2 + i * stepX;
      const y = height - 2 - ((p.value - min) / range) * (height - 4);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const first = values[0];
  const last = values[values.length - 1];
  const arrow = trendArrow(first, last);
  const arrowClass = trendColor(first, last);

  return (
    <span
      className="inline-flex items-center gap-1.5 align-middle"
      title={`${metric.replace(/_/g, " ")}: ${first.toFixed(0)} → ${last.toFixed(0)} over ${points.length} snapshots`}
      aria-label={`Trend: ${first.toFixed(0)} to ${last.toFixed(0)}, last ${points.length} snapshots`}
      data-testid="quality-sparkline"
    >
      <svg width={width} height={height} aria-hidden>
        <polyline
          fill="none"
          stroke="#6366f1"
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
          points={polylinePoints}
        />
        {points.map((p, i) => {
          if (!EVENT_SOURCES.has(p.source)) return null;
          const x = 2 + i * stepX;
          const y = height - 2 - ((p.value - min) / range) * (height - 4);
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={1.8}
              fill={p.source === "promotion" ? "#16a34a" : "#0ea5e9"}
              data-source={p.source}
            />
          );
        })}
      </svg>
      <span className={`text-[10px] font-medium ${arrowClass}`}>{arrow}</span>
    </span>
  );
}
