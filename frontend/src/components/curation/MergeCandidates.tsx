"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { PaginatedResponse } from "@/lib/api-client";
import type {
  MergeCandidate,
  MergeExplanation,
  FieldExplanation,
} from "@/types/entity-resolution";

interface MergeCandidatesProps {
  onAcceptMerge?: (candidate: MergeCandidate) => void;
  onCandidateHover?: (candidate: MergeCandidate | null) => void;
  onCandidatesLoaded?: (candidates: MergeCandidate[]) => void;
}

const FIELD_LABELS: Record<string, string> = {
  label_sim: "Label",
  description_sim: "Description",
  uri_sim: "URI",
  topology_sim: "Topology",
};

const PAGE_SIZE = 20;

function scoreBarColor(score: number): string {
  if (score >= 0.8) return "bg-green-500";
  if (score >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

function scoreBarGradient(score: number): string {
  if (score >= 0.8) return "from-green-400 to-green-600";
  if (score >= 0.5) return "from-yellow-400 to-yellow-600";
  return "from-red-400 to-red-600";
}

function methodLabel(method: string): string {
  return method.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function MergeCandidates({
  onAcceptMerge,
  onCandidateHover,
  onCandidatesLoaded,
}: MergeCandidatesProps) {
  const [candidates, setCandidates] = useState<MergeCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scoreThreshold, setScoreThreshold] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [expandedPairId, setExpandedPairId] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<MergeExplanation | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchCandidates = useCallback(
    async (append = false) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          sort: "score_desc",
        });
        if (append && cursor) {
          params.set("cursor", cursor);
        }
        const res = await api.get<PaginatedResponse<MergeCandidate>>(
          `/api/v1/er/candidates?${params}`,
        );
        const updated = append ? [...candidates, ...res.data] : res.data;
        setCandidates(updated);
        setCursor(res.cursor);
        setHasMore(res.has_more);
        setTotalCount(res.total_count);
        onCandidatesLoaded?.(updated);
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.body.message
            : "Failed to load candidates",
        );
      } finally {
        setLoading(false);
      }
    },
    [cursor, candidates, onCandidatesLoaded],
  );

  useEffect(() => {
    fetchCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredCandidates = useMemo(
    () => candidates.filter((c) => c.overall_score >= scoreThreshold),
    [candidates, scoreThreshold],
  );

  const handleExplain = useCallback(async (pairId: string) => {
    setExpandedPairId((prev) => (prev === pairId ? null : pairId));
    setExplainLoading(true);
    setExplanation(null);
    try {
      const res = await api.get<MergeExplanation>(
        `/api/v1/er/candidates/${pairId}/explain`,
      );
      setExplanation(res);
    } catch {
      setExplanation(null);
    } finally {
      setExplainLoading(false);
    }
  }, []);

  const handleAccept = useCallback(
    async (candidate: MergeCandidate) => {
      setActionLoading(candidate.pair_id);
      try {
        await api.post(`/api/v1/er/candidates/${candidate.pair_id}/accept`);
        setCandidates((prev) =>
          prev.map((c) =>
            c.pair_id === candidate.pair_id
              ? { ...c, status: "accepted" }
              : c,
          ),
        );
        onAcceptMerge?.(candidate);
      } catch {
        /* optimistic UI already applied */
      } finally {
        setActionLoading(null);
      }
    },
    [onAcceptMerge],
  );

  const handleReject = useCallback(async (pairId: string) => {
    setActionLoading(pairId);
    try {
      await api.post(`/api/v1/er/candidates/${pairId}/reject`);
      setCandidates((prev) =>
        prev.map((c) =>
          c.pair_id === pairId ? { ...c, status: "rejected" } : c,
        ),
      );
    } catch {
      /* silent */
    } finally {
      setActionLoading(null);
    }
  }, []);

  return (
    <div className="flex flex-col h-full" data-testid="merge-candidates">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-900">
            Merge Candidates
          </h2>
          <span className="text-xs text-gray-500">
            {filteredCandidates.length} of {totalCount}
          </span>
        </div>

        {/* Score threshold slider */}
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-500 whitespace-nowrap">
            Min score
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={scoreThreshold * 100}
            onChange={(e) => setScoreThreshold(Number(e.target.value) / 100)}
            className="flex-1 h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600"
            data-testid="score-threshold-slider"
          />
          <span
            className="text-xs font-mono text-gray-600 w-10 text-right"
            data-testid="score-threshold-value"
          >
            {(scoreThreshold * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Candidate list */}
      <div className="flex-1 overflow-y-auto">
        {loading && candidates.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-400 animate-pulse">
              Loading candidates...
            </p>
          </div>
        )}

        {error && (
          <div className="p-4 m-4 bg-red-50 rounded-lg">
            <p className="text-sm text-red-600">{error}</p>
            <button
              onClick={() => fetchCandidates()}
              className="mt-2 text-xs text-blue-600 hover:text-blue-800"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && filteredCandidates.length === 0 && (
          <div className="p-8 text-center" data-testid="no-candidates">
            <p className="text-sm text-gray-400">
              {candidates.length === 0
                ? "No merge candidates found"
                : "No candidates above the score threshold"}
            </p>
          </div>
        )}

        <ul className="divide-y divide-gray-100">
          {filteredCandidates.map((candidate) => (
            <CandidateRow
              key={candidate.pair_id}
              candidate={candidate}
              expanded={expandedPairId === candidate.pair_id}
              explanation={
                expandedPairId === candidate.pair_id ? explanation : null
              }
              explainLoading={
                expandedPairId === candidate.pair_id && explainLoading
              }
              actionLoading={actionLoading === candidate.pair_id}
              onExplain={handleExplain}
              onAccept={handleAccept}
              onReject={handleReject}
              onHover={onCandidateHover}
            />
          ))}
        </ul>

        {/* Load more */}
        {hasMore && (
          <div className="p-4 text-center">
            <button
              onClick={() => fetchCandidates(true)}
              disabled={loading}
              className="text-xs px-4 py-1.5 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              data-testid="load-more-btn"
            >
              {loading ? "Loading..." : "Load more"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Candidate Row ---

interface CandidateRowProps {
  candidate: MergeCandidate;
  expanded: boolean;
  explanation: MergeExplanation | null;
  explainLoading: boolean;
  actionLoading: boolean;
  onExplain: (pairId: string) => void;
  onAccept: (candidate: MergeCandidate) => void;
  onReject: (pairId: string) => void;
  onHover?: (candidate: MergeCandidate | null) => void;
}

function CandidateRow({
  candidate,
  expanded,
  explanation,
  explainLoading,
  actionLoading,
  onExplain,
  onAccept,
  onReject,
  onHover,
}: CandidateRowProps) {
  const isResolved = candidate.status !== "pending";

  return (
    <li
      className={`px-4 py-3 transition-colors ${isResolved ? "opacity-60" : "hover:bg-gray-50"}`}
      data-testid={`candidate-${candidate.pair_id}`}
      onMouseEnter={() => !isResolved && onHover?.(candidate)}
      onMouseLeave={() => onHover?.(null)}
    >
      {/* Entity labels */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium text-gray-800 truncate flex-1">
          {candidate.entity_1.label}
        </span>
        <span className="text-xs text-gray-400">&#8596;</span>
        <span className="text-sm font-medium text-gray-800 truncate flex-1 text-right">
          {candidate.entity_2.label}
        </span>
      </div>

      {/* Overall score bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full bg-gradient-to-r ${scoreBarGradient(candidate.overall_score)}`}
            style={{ width: `${candidate.overall_score * 100}%` }}
            data-testid={`score-bar-${candidate.pair_id}`}
          />
        </div>
        <span className="text-xs font-mono text-gray-600 w-10 text-right">
          {(candidate.overall_score * 100).toFixed(0)}%
        </span>
      </div>

      {/* Field scores mini-view */}
      <div className="grid grid-cols-4 gap-1 mb-2">
        {Object.entries(candidate.field_scores).map(([field, score]) => (
          <div key={field} className="text-center">
            <div className="text-[10px] text-gray-400 mb-0.5">
              {FIELD_LABELS[field] ?? field}
            </div>
            <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${scoreBarColor(score)}`}
                style={{ width: `${score * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Status badge + actions */}
      <div className="flex items-center gap-2">
        {isResolved && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              candidate.status === "accepted"
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}
            data-testid={`status-${candidate.pair_id}`}
          >
            {candidate.status === "accepted" ? "Accepted" : "Rejected"}
          </span>
        )}

        {!isResolved && (
          <div className="flex items-center gap-1.5 ml-auto">
            <button
              onClick={() => onExplain(candidate.pair_id)}
              className="text-xs px-2.5 py-1 border border-gray-300 rounded-md text-gray-600 hover:bg-gray-50"
              data-testid={`explain-btn-${candidate.pair_id}`}
            >
              {expanded ? "Hide" : "Explain"}
            </button>
            <button
              onClick={() => onAccept(candidate)}
              disabled={actionLoading}
              className="text-xs px-2.5 py-1 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
              data-testid={`accept-btn-${candidate.pair_id}`}
            >
              Accept
            </button>
            <button
              onClick={() => onReject(candidate.pair_id)}
              disabled={actionLoading}
              className="text-xs px-2.5 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50"
              data-testid={`reject-btn-${candidate.pair_id}`}
            >
              Reject
            </button>
          </div>
        )}
      </div>

      {/* Explanation panel */}
      {expanded && (
        <div
          className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-200"
          data-testid={`explanation-${candidate.pair_id}`}
        >
          {explainLoading && (
            <p className="text-xs text-gray-400 animate-pulse">
              Loading explanation...
            </p>
          )}
          {!explainLoading && explanation && (
            <ExplanationDetail fields={explanation.fields} />
          )}
          {!explainLoading && !explanation && (
            <p className="text-xs text-gray-400">
              Could not load explanation.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

// --- Explanation Detail ---

function ExplanationDetail({ fields }: { fields: FieldExplanation[] }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-gray-700">
        Field-by-Field Comparison
      </h4>
      <table className="w-full text-xs" data-testid="explanation-table">
        <thead>
          <tr className="text-left text-gray-500 border-b border-gray-200">
            <th className="pb-1 pr-2">Field</th>
            <th className="pb-1 pr-2">Entity 1</th>
            <th className="pb-1 pr-2">Entity 2</th>
            <th className="pb-1 pr-2">Score</th>
            <th className="pb-1">Method</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {fields.map((f) => (
            <tr key={f.field_name}>
              <td className="py-1.5 pr-2 font-medium text-gray-700">
                {f.field_name}
              </td>
              <td className="py-1.5 pr-2 text-gray-600 truncate max-w-[120px]">
                {f.value_1}
              </td>
              <td className="py-1.5 pr-2 text-gray-600 truncate max-w-[120px]">
                {f.value_2}
              </td>
              <td className="py-1.5 pr-2">
                <div className="flex items-center gap-1">
                  <div className="w-12 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${scoreBarColor(f.similarity)}`}
                      style={{ width: `${f.similarity * 100}%` }}
                    />
                  </div>
                  <span className="text-gray-500">
                    {(f.similarity * 100).toFixed(0)}%
                  </span>
                </div>
              </td>
              <td className="py-1.5 text-gray-400">{methodLabel(f.method)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
