"use client";

/**
 * CQ Coverage tile (Stream 22 / CQ-PR6, PRD §6.19 FR-19.11).
 *
 * Dashboard card for one ontology's competency-question coverage:
 *
 * - On mount it fetches the *open gap backlog* via ``GET /coverage/gaps`` — a
 *   cheap read that never executes CQ queries, so the dashboard stays fast.
 * - "Check coverage" runs ``POST /coverage?gate=true&persist_gaps=true``, which
 *   evaluates every CQ, refreshes the backlog, and returns the coverage %, the
 *   per-use-case breakdown, and the release-readiness gate signal (FR-19.8).
 *
 * The heavier full authoring/coverage surface lives in the workspace
 * ``RequirementsOverlay``; this tile is the at-a-glance dashboard view.
 */

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api-client";

interface Gap {
  text?: string;
  cq_text?: string;
  use_case?: string | null;
  priority?: string | null;
  status?: string;
  gap_kind?: string;
}

interface ReleaseGate {
  passed: boolean;
  required_pct: number;
  actual_pct: number;
  considered: number;
  answerable: number;
}

interface CoverageReport {
  coverage_pct: number;
  total: number;
  answerable: number;
  by_use_case: Record<string, { total: number; answerable: number }>;
  gaps: Gap[];
  release_gate?: ReleaseGate;
}

interface GapsResponse {
  gaps: Gap[];
  count: number;
}

function gapLabel(g: Gap): string {
  return g.cq_text ?? g.text ?? "(untitled question)";
}

function pctColor(pct: number): string {
  if (pct >= 80) return "text-green-600";
  if (pct >= 50) return "text-yellow-600";
  return "text-red-600";
}

interface Props {
  ontologyId: string;
  ontologyName?: string;
}

export default function CQCoverageTile({ ontologyId, ontologyName }: Props) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [gapsLoaded, setGapsLoaded] = useState(false);
  const [report, setReport] = useState<CoverageReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const path = `/api/v1/ontology/${encodeURIComponent(ontologyId)}`;

  const loadGaps = useCallback(async () => {
    try {
      const res = await api.get<GapsResponse>(`${path}/coverage/gaps`);
      setGaps(res.gaps ?? []);
      setError(null);
    } catch (e) {
      // No spec / no backlog yet is not an error worth shouting about.
      if (e instanceof ApiError && e.status === 404) {
        setGaps([]);
      } else {
        setError(e instanceof Error ? e.message : "failed to load gaps");
      }
    } finally {
      setGapsLoaded(true);
    }
  }, [path]);

  useEffect(() => {
    setReport(null);
    setGapsLoaded(false);
    void loadGaps();
  }, [loadGaps]);

  const runCoverage = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await api.post<CoverageReport>(
        `${path}/coverage?gate=true&persist_gaps=true`,
      );
      setReport(res);
      setGaps(res.gaps ?? []);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("No requirements spec — add competency questions first.");
      } else {
        setError(e instanceof Error ? e.message : "coverage check failed");
      }
    } finally {
      setRunning(false);
    }
  }, [path]);

  const gate = report?.release_gate;

  return (
    <div
      className="bg-white rounded-lg border border-gray-200 p-4"
      data-testid="cq-coverage-tile"
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          CQ Coverage{ontologyName ? ` — ${ontologyName}` : ""}
        </p>
        <button
          type="button"
          onClick={() => void runCoverage()}
          disabled={running}
          data-testid="cq-coverage-run"
          className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50"
        >
          {running ? "Checking…" : "Check coverage"}
        </button>
      </div>

      {report ? (
        <div className="mt-2 flex items-baseline gap-3">
          <span
            className={`text-2xl font-bold ${pctColor(report.coverage_pct)}`}
            data-testid="cq-coverage-pct"
          >
            {report.coverage_pct.toFixed(0)}%
          </span>
          <span className="text-xs text-gray-400">
            {report.answerable}/{report.total} answerable
          </span>
        </div>
      ) : (
        <p className="mt-2 text-xs text-gray-400">
          {gapsLoaded
            ? `${gaps.length} open gap${gaps.length === 1 ? "" : "s"} — run a check for coverage %`
            : "Loading…"}
        </p>
      )}

      {gate && (
        <div
          className={`mt-2 inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${
            gate.passed ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
          }`}
          data-testid="cq-coverage-gate"
        >
          Release gate: {gate.passed ? "PASS" : "FAIL"} (priority {gate.actual_pct.toFixed(0)}% /{" "}
          {gate.required_pct.toFixed(0)}% required)
        </div>
      )}

      {report && Object.keys(report.by_use_case).length > 0 && (
        <div className="mt-3 space-y-1">
          {Object.entries(report.by_use_case).map(([uc, b]) => {
            const pct = b.total > 0 ? (b.answerable / b.total) * 100 : 0;
            return (
              <div key={uc} className="flex items-center gap-2 text-xs">
                <span className="w-28 truncate text-gray-600" title={uc}>
                  {uc}
                </span>
                <div className="h-1.5 flex-1 rounded bg-gray-100">
                  <div
                    className="h-1.5 rounded bg-blue-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-10 text-right text-gray-400">
                  {b.answerable}/{b.total}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {gaps.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-gray-500">
            Open gaps ({gaps.length})
          </p>
          <ul className="mt-1 space-y-1" data-testid="cq-coverage-gaps">
            {gaps.slice(0, 8).map((g, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600">
                <span className="mt-0.5 text-red-400">•</span>
                <span className="flex-1">{gapLabel(g)}</span>
                {g.priority && (
                  <span className="text-gray-400">[{g.priority}]</span>
                )}
              </li>
            ))}
            {gaps.length > 8 && (
              <li className="text-xs text-gray-400">+{gaps.length - 8} more…</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
