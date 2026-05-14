"use client";

/**
 * Q.5 — Curation throughput badge for the curation page header.
 *
 * Shows "N concepts/hour" derived from the client-side throughput
 * tracker (which times the gap between consecutive submit clicks, not
 * wall-clock — see ``lib/curationThroughput``).
 *
 * Two readings are rendered together so the curator can see whether
 * they're speeding up or slowing down:
 *
 *   - Session average (``deriveConceptsPerHour``)
 *   - Trailing 10-decision rate (``deriveTrailingRate``)
 *
 * Visual states:
 *   - No decisions yet → discreet "—" placeholder.
 *   - Trailing rate > session rate by 10 % → emerald "↑" hint.
 *   - Trailing rate < session rate by 10 % → rose "↓" hint.
 */

import { useEffect, useState } from "react";

import {
  deriveConceptsPerHour,
  deriveTrailingRate,
  getCurationThroughputState,
  subscribeCurationThroughput,
  type CurationThroughputState,
} from "@/lib/curationThroughput";

function fmtRate(rate: number | null): string {
  if (rate == null) return "—";
  if (rate >= 100) return `${Math.round(rate)}`;
  if (rate >= 10) return rate.toFixed(1);
  return rate.toFixed(2);
}

function trendHint(session: number | null, trailing: number | null): {
  arrow: string;
  className: string;
  label: string;
} {
  if (session == null || trailing == null || session <= 0) {
    return { arrow: "", className: "text-gray-400", label: "" };
  }
  const ratio = trailing / session;
  if (ratio > 1.1) {
    return { arrow: "↑", className: "text-emerald-600", label: "speeding up" };
  }
  if (ratio < 0.9) {
    return { arrow: "↓", className: "text-rose-600", label: "slowing down" };
  }
  return { arrow: "→", className: "text-gray-500", label: "steady" };
}

export interface CurationThroughputCounterProps {
  /** Compact badge (header) vs full pill (sidebar). Defaults to compact. */
  variant?: "compact" | "full";
}

export default function CurationThroughputCounter({
  variant = "compact",
}: CurationThroughputCounterProps) {
  const [snap, setSnap] = useState<CurationThroughputState>(() =>
    getCurationThroughputState(),
  );

  useEffect(() => {
    return subscribeCurationThroughput(setSnap);
  }, []);

  // Re-derive on every state change; cheap O(N) over capped recent list.
  const sessionRate = deriveConceptsPerHour(snap);
  const trailingRate = deriveTrailingRate(snap, 10);
  const trend = trendHint(sessionRate, trailingRate);

  if (variant === "full") {
    return (
      <div
        className="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm"
        data-testid="curation-throughput-counter"
        aria-label="Curation throughput"
      >
        <div className="text-xs uppercase tracking-wide text-gray-400">Throughput</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-gray-900">
            {fmtRate(sessionRate)}
          </span>
          <span className="text-xs text-gray-500">concepts / hour (session)</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-xs text-gray-500">
          <span className={`font-medium ${trend.className}`}>
            {trend.arrow || "·"}
          </span>
          <span>{fmtRate(trailingRate)} last 10</span>
          {trend.label && (
            <span className="text-gray-400">({trend.label})</span>
          )}
        </div>
        <div className="mt-1 text-[10px] text-gray-400">
          {snap.decisionCount} decisions · {(snap.activeTimeMs / 1000).toFixed(0)}s active
        </div>
      </div>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-gray-50 px-3 py-1 text-xs"
      data-testid="curation-throughput-counter"
      title={
        sessionRate == null
          ? "No decisions recorded yet this session"
          : `Session: ${fmtRate(sessionRate)} concepts/hour over ${snap.decisionCount} decisions; trailing 10: ${fmtRate(trailingRate)}/hour`
      }
      aria-label={
        sessionRate == null
          ? "Throughput: no data"
          : `Throughput: ${fmtRate(sessionRate)} concepts per hour, ${trend.label || "steady"}`
      }
    >
      <span className="text-gray-400" aria-hidden>⏱</span>
      <span className="font-semibold tabular-nums text-gray-700">
        {fmtRate(sessionRate)}
      </span>
      <span className="text-gray-500">/hr</span>
      {trend.arrow && (
        <span className={`font-medium ${trend.className}`}>{trend.arrow}</span>
      )}
    </span>
  );
}
