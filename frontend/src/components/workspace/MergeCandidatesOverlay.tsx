"use client";

/**
 * Merge Candidates overlay (Stream 2 PR 1).
 *
 * Triggers an ER pipeline run for the open ontology, polls until it
 * completes, and lets the curator accept / reject / inspect each
 * candidate duplicate pair without leaving the workspace canvas. Per
 * ``ui-architecture.mdc``:
 *
 *  - Overlay over the workspace canvas, never a route (rule 9).
 *  - Placement is ``viewportTopRight`` so it stacks with revisions /
 *    feedback overlays in the same zone but on different stack
 *    indices (rule 10) -- not on top of the asset-info panel.
 *  - Decisions are reversible and apply optimistically; backend
 *    rejection of an already-merged pair will surface as a toast and
 *    re-fetch will restore the row's true state (rule 18).
 *  - Esc closes the explanation pane first, then the overlay (matches
 *    the Revisions Inbox shortcut convention).
 *
 * The component talks to the real backend at:
 *
 *   POST /api/v1/er/run                              -- trigger run
 *   GET  /api/v1/er/runs/{run_id}                    -- poll status
 *   GET  /api/v1/er/runs/{run_id}/candidates         -- list pairs
 *   POST /api/v1/er/candidates/{pair_id}/accept      -- merge pair
 *   POST /api/v1/er/candidates/{pair_id}/reject      -- dismiss pair
 *   GET  /api/v1/er/candidates/{pair_id}/explain     -- field detail
 *
 * NOT the aspirational `/api/v1/er/candidates` endpoints the deprecated
 * `/entity-resolution` page binds to -- those don't exist on the
 * backend.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Wire types -- mirror the actual backend (see app/services/er.py and
// app/api/er.py).
// ---------------------------------------------------------------------------

interface ERRunResponse {
  run_id: string;
  status: string;
  candidate_count: number;
  cluster_count: number;
  duration_seconds: number;
  error: string | null;
}

interface CandidateRow {
  pair_id: string;
  source_key: string;
  source_label: string;
  source_uri: string;
  target_key: string;
  target_label: string;
  target_uri: string;
  combined_score: number;
  field_scores: Record<string, number>;
  topological_score: number;
  accepted_at: number | null;
  rejected_at: number | null;
}

interface CandidatesListResponse {
  data: CandidateRow[];
  total_count: number;
}

interface ExplainResponse {
  pair_id: string;
  key1: string;
  key2: string;
  class_1: { label: string; uri: string };
  class_2: { label: string; uri: string };
  field_scores: Record<string, number>;
  combined_score: number;
}

interface AcceptResponse {
  pair_id: string;
  status: "accepted" | "already_accepted";
  accepted_at: number;
  merge_result?: {
    target_key: string;
    source_key: string;
    strategy: string;
  };
}

interface RejectResponse {
  pair_id: string;
  status: "rejected" | "already_rejected";
  rejected_at: number;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
  /** Called after every successful accept/reject so the parent can
   *  refresh the canvas, sidebar counters, etc. */
  onChanged?: () => void;
}

// ---------------------------------------------------------------------------
// Visual helpers
// ---------------------------------------------------------------------------

function scoreBarColor(score: number): string {
  if (score >= 0.85) return "from-emerald-400 to-emerald-600";
  if (score >= 0.7) return "from-amber-400 to-amber-600";
  return "from-rose-400 to-rose-600";
}

function fieldDisplayName(field: string): string {
  // The backend uses `label_jaro_winkler`, `description_token_overlap`,
  // `uri_exact`, `topological` -- humanise for display without losing
  // the algorithm hint.
  return field
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MergeCandidatesOverlay({
  ontologyId,
  ontologyName,
  onClose,
  onChanged,
}: Props) {
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>("pending");
  const [runError, setRunError] = useState<string | null>(null);

  const [rows, setRows] = useState<CandidateRow[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [busyPair, setBusyPair] = useState<string | null>(null);
  const [expandedPair, setExpandedPair] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<ExplainResponse | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);

  const [toast, setToast] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0.7);

  // ---- Esc to close ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (expandedPair) {
        setExpandedPair(null);
      } else {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, expandedPair]);

  // ---- Trigger an ER run on mount ----
  // The backend route is synchronous today (the pipeline blocks the
  // request), but we still treat the response as the start of a run
  // so a future async refactor (Celery worker, polling) won't require
  // re-wiring the UI.
  useEffect(() => {
    let cancelled = false;
    setRunStatus("running");
    setRunError(null);
    setRows([]);
    setExpandedPair(null);
    setExplanation(null);

    (async () => {
      try {
        const res = await api.post<ERRunResponse>("/api/v1/er/run", {
          ontology_id: ontologyId,
        });
        if (cancelled) return;
        setRunId(res.run_id);
        setRunStatus(res.status);
        if (res.error) {
          setRunError(res.error);
        }
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to start ER pipeline";
        setRunError(msg);
        setRunStatus("failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  // ---- Fetch candidates once the run completes ----
  const fetchCandidates = useCallback(async () => {
    if (!runId) return;
    setLoadingRows(true);
    setListError(null);
    try {
      const res = await api.get<CandidatesListResponse>(
        `/api/v1/er/runs/${encodeURIComponent(runId)}/candidates?limit=200&min_score=0`,
      );
      setRows(res.data ?? []);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error
            ? err.message
            : "Failed to load candidates";
      setListError(msg);
    } finally {
      setLoadingRows(false);
    }
  }, [runId]);

  useEffect(() => {
    if (runStatus === "complete" || runStatus === "completed") {
      void fetchCandidates();
    }
  }, [runStatus, fetchCandidates]);

  // ---- Filter by min-score slider ----
  const visibleRows = useMemo(
    () => rows.filter((r) => r.combined_score >= minScore),
    [rows, minScore],
  );

  // ---- Decisions ----
  const decide = useCallback(
    async (pair: CandidateRow, verb: "accept" | "reject") => {
      setBusyPair(pair.pair_id);
      try {
        if (verb === "accept") {
          const res = await api.post<AcceptResponse>(
            `/api/v1/er/candidates/${encodeURIComponent(pair.pair_id)}/accept`,
          );
          setToast(
            res.status === "already_accepted"
              ? `Already merged.`
              : `Merged "${pair.source_label}" → "${pair.target_label}".`,
          );
        } else {
          const res = await api.post<RejectResponse>(
            `/api/v1/er/candidates/${encodeURIComponent(pair.pair_id)}/reject`,
          );
          setToast(
            res.status === "already_rejected"
              ? "Already dismissed."
              : `Dismissed candidate.`,
          );
        }
        // Optimistic local removal -- the decision endpoint already
        // soft-marked the edge, so a fresh fetch would re-confirm
        // this. Removing locally keeps the row count snappy.
        setRows((prev) => prev.filter((r) => r.pair_id !== pair.pair_id));
        if (expandedPair === pair.pair_id) setExpandedPair(null);
        onChanged?.();
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : `${verb} failed`;
        setToast(msg);
      } finally {
        setBusyPair(null);
      }
    },
    [expandedPair, onChanged],
  );

  // ---- Explain (expand row) ----
  //
  // Click on an already-expanded row collapses without re-fetching.
  // Click on a different row collapses the old one and fetches the
  // new explanation. The fetch only fires when we are *transitioning
  // from collapsed to expanded* for this row.
  const toggleExplain = useCallback(
    async (pair: CandidateRow) => {
      const wasExpanded = expandedPair === pair.pair_id;
      setExpandedPair(wasExpanded ? null : pair.pair_id);
      setExplanation(null);
      if (wasExpanded) return;

      setExplainLoading(true);
      try {
        const res = await api.get<ExplainResponse>(
          `/api/v1/er/candidates/${encodeURIComponent(pair.pair_id)}/explain`,
        );
        setExplanation(res);
      } catch {
        setExplanation(null);
      } finally {
        setExplainLoading(false);
      }
    },
    [expandedPair],
  );

  // ---- Toast auto-dismiss ----
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(t);
  }, [toast]);

  const isRunning = runStatus !== "complete" && runStatus !== "completed" && runStatus !== "failed";
  const isFailed = runStatus === "failed" || !!runError;

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[600px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label={`Merge Candidates for ${ontologyName}`}
      data-testid="merge-candidates-overlay"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Merge Candidates
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            <span className="font-medium text-slate-700">{ontologyName}</span>
            {" · "}
            {isRunning
              ? "running ER pipeline…"
              : isFailed
                ? "pipeline failed"
                : `${visibleRows.length} of ${rows.length} pair${rows.length === 1 ? "" : "s"} above ${(minScore * 100).toFixed(0)}%`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {runId && !isRunning && (
            <button
              type="button"
              onClick={() => void fetchCandidates()}
              className="text-xs font-medium text-slate-500 hover:text-slate-800"
              title="Refresh candidates"
              data-testid="merge-candidates-refresh"
            >
              ↻
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-700 text-xl leading-none"
            data-testid="merge-candidates-close"
          >
            ×
          </button>
        </div>
      </div>

      {/* Threshold slider -- only after the run finishes, otherwise it
          jitters the layout while results stream in. */}
      {!isRunning && !isFailed && (
        <div className="px-5 py-2 border-b border-slate-100 flex items-center gap-3">
          <label className="text-xs text-slate-500 whitespace-nowrap">
            Min score
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={minScore * 100}
            onChange={(e) => setMinScore(Number(e.target.value) / 100)}
            className="flex-1 h-1.5 bg-slate-200 rounded-full appearance-none cursor-pointer accent-indigo-600"
            data-testid="merge-min-score-slider"
          />
          <span className="text-xs font-mono text-slate-600 w-10 text-right">
            {(minScore * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {isRunning && (
          <div className="p-8 text-center" data-testid="merge-running">
            <p className="text-sm text-slate-400 animate-pulse">
              Scanning ontology for duplicates…
            </p>
            <p className="mt-2 text-xs text-slate-400">
              This compares every class label, description, URI, and
              graph neighborhood. Larger ontologies take longer.
            </p>
          </div>
        )}

        {isFailed && (
          <div className="p-6" data-testid="merge-failed">
            <div className="bg-rose-50 border border-rose-200 rounded-lg p-4">
              <p className="text-sm font-medium text-rose-700">
                ER pipeline failed
              </p>
              <p className="mt-1 text-xs text-rose-600">
                {runError ?? "Unknown error"}
              </p>
            </div>
          </div>
        )}

        {!isRunning && !isFailed && loadingRows && rows.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-sm text-slate-400 animate-pulse">
              Loading candidates…
            </p>
          </div>
        )}

        {!isRunning && !isFailed && !loadingRows && listError && (
          <div className="p-6">
            <div className="bg-rose-50 border border-rose-200 rounded-lg p-4">
              <p className="text-sm text-rose-600">{listError}</p>
              <button
                type="button"
                onClick={() => void fetchCandidates()}
                className="mt-2 text-xs text-indigo-600 hover:text-indigo-800"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {!isRunning && !isFailed && !loadingRows && !listError && visibleRows.length === 0 && (
          <div className="p-8 text-center" data-testid="merge-empty">
            <p className="text-sm text-slate-400">
              {rows.length === 0
                ? "No duplicate candidates found."
                : "No candidates above the score threshold."}
            </p>
          </div>
        )}

        <ul className="divide-y divide-slate-100" data-testid="merge-list">
          {visibleRows.map((pair) => (
            <CandidateListItem
              key={pair.pair_id}
              pair={pair}
              expanded={expandedPair === pair.pair_id}
              explanation={expandedPair === pair.pair_id ? explanation : null}
              explainLoading={expandedPair === pair.pair_id && explainLoading}
              busy={busyPair === pair.pair_id}
              onAccept={() => void decide(pair, "accept")}
              onReject={() => void decide(pair, "reject")}
              onExplain={() => void toggleExplain(pair)}
            />
          ))}
        </ul>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-xs px-3 py-2 rounded-lg shadow-lg pointer-events-none"
          data-testid="merge-toast"
        >
          {toast}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface RowProps {
  pair: CandidateRow;
  expanded: boolean;
  explanation: ExplainResponse | null;
  explainLoading: boolean;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
  onExplain: () => void;
}

function CandidateListItem({
  pair,
  expanded,
  explanation,
  explainLoading,
  busy,
  onAccept,
  onReject,
  onExplain,
}: RowProps) {
  return (
    <li
      className="px-5 py-3 hover:bg-slate-50 transition-colors"
      data-testid={`merge-row-${pair.pair_id}`}
    >
      {/* Labels */}
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className="text-sm font-medium text-slate-800 truncate flex-1"
          title={pair.source_uri}
        >
          {pair.source_label}
        </span>
        <span className="text-xs text-slate-400">↔</span>
        <span
          className="text-sm font-medium text-slate-800 truncate flex-1 text-right"
          title={pair.target_uri}
        >
          {pair.target_label}
        </span>
      </div>

      {/* Score bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full bg-gradient-to-r ${scoreBarColor(pair.combined_score)}`}
            style={{ width: `${pair.combined_score * 100}%` }}
            data-testid={`merge-score-bar-${pair.pair_id}`}
          />
        </div>
        <span className="text-xs font-mono text-slate-600 w-10 text-right">
          {(pair.combined_score * 100).toFixed(0)}%
        </span>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 justify-end">
        <button
          type="button"
          onClick={onExplain}
          disabled={busy}
          className="text-xs px-2.5 py-1 border border-slate-300 rounded-md text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          data-testid={`merge-explain-btn-${pair.pair_id}`}
        >
          {expanded ? "Hide" : "Explain"}
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={busy}
          className="text-xs px-2.5 py-1 border border-rose-200 text-rose-700 rounded-md hover:bg-rose-50 disabled:opacity-50"
          data-testid={`merge-reject-btn-${pair.pair_id}`}
        >
          Dismiss
        </button>
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="text-xs px-2.5 py-1 bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50"
          data-testid={`merge-accept-btn-${pair.pair_id}`}
        >
          Merge
        </button>
      </div>

      {/* Explanation panel */}
      {expanded && (
        <div
          className="mt-3 p-3 bg-slate-50 rounded-lg border border-slate-200"
          data-testid={`merge-explanation-${pair.pair_id}`}
        >
          {explainLoading && (
            <p className="text-xs text-slate-400 animate-pulse">
              Loading explanation…
            </p>
          )}
          {!explainLoading && explanation && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="pb-1 pr-2 font-medium">Field</th>
                  <th className="pb-1 text-right font-medium">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {Object.entries(explanation.field_scores).map(([field, score]) => (
                  <tr key={field}>
                    <td className="py-1.5 pr-2 text-slate-700">
                      {fieldDisplayName(field)}
                    </td>
                    <td className="py-1.5 text-right">
                      <div className="inline-flex items-center gap-1">
                        <div className="w-16 h-1 bg-slate-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full bg-gradient-to-r ${scoreBarColor(score)}`}
                            style={{ width: `${score * 100}%` }}
                          />
                        </div>
                        <span className="font-mono text-slate-600 w-9 text-right">
                          {(score * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!explainLoading && !explanation && (
            <p className="text-xs text-slate-400">
              Explanation unavailable.
            </p>
          )}
        </div>
      )}
    </li>
  );
}
