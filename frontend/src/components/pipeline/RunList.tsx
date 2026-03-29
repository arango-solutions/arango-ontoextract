"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api-client";
import type { PaginatedResponse } from "@/lib/api-client";
import type { ExtractionRun, RunStatus } from "@/types/pipeline";
import StatusBadge from "@/components/ui/StatusBadge";

interface RunListProps {
  onSelectRun: (runId: string) => void;
  selectedRunId?: string | null;
}

const STATUS_OPTIONS: { value: RunStatus | "all"; label: string }[] = [
  { value: "all", label: "All Statuses" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "paused", label: "Paused" },
];

const AUTO_REFRESH_MS = 5_000;

function formatRelativeTime(value: string | number | undefined): string {
  if (value == null) return "";
  const now = Date.now();
  const then = typeof value === "number" ? value * 1000 : new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = now - then;
  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms === null) return "\u2014";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSec = seconds % 60;
  return `${minutes}m ${remainingSec}s`;
}

function truncateId(id: string, maxLen = 12): string {
  return id.length > maxLen ? `${id.slice(0, maxLen)}\u2026` : id;
}

export default function RunList({ onSelectRun, selectedRunId }: RunListProps) {
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<RunStatus | "all">("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRuns = useCallback(
    async (append = false, nextCursor?: string | null) => {
      try {
        if (!append) setLoading(true);
        const params = new URLSearchParams({
          sort: "created_at",
          order: "desc",
          limit: "25",
        });
        if (statusFilter !== "all") params.set("status", statusFilter);
        if (append && nextCursor) params.set("cursor", nextCursor);

        const res = await api.get<PaginatedResponse<ExtractionRun>>(
          `/api/v1/extraction/runs?${params.toString()}`,
        );

        if (append) {
          setRuns((prev) => [...prev, ...res.data]);
        } else {
          setRuns(res.data);
        }
        setCursor(res.cursor);
        setHasMore(res.has_more);
        setTotalCount(res.total_count);
      } catch {
        // API unavailable — keep existing data
      } finally {
        setLoading(false);
      }
    },
    [statusFilter],
  );

  useEffect(() => {
    fetchRuns(false);
  }, [fetchRuns]);

  useEffect(() => {
    const hasActiveRuns = runs.some(
      (r) => r.status === "running" || r.status === "queued",
    );
    if (hasActiveRuns) {
      refreshTimerRef.current = setInterval(() => fetchRuns(false), AUTO_REFRESH_MS);
    }
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, [runs, fetchRuns]);

  return (
    <div className="flex flex-col h-full" data-testid="run-list">
      <div className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Extraction Runs
          </h2>
          <span className="text-xs text-gray-400">{totalCount} total</span>
        </div>
        <select
          value={statusFilter}
          onChange={(e) =>
            setStatusFilter(e.target.value as RunStatus | "all")
          }
          className="w-full text-sm border border-gray-300 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="status-filter"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && runs.length === 0 ? (
          <div className="p-4 space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-16 bg-gray-100 rounded-lg animate-pulse"
              />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <div className="p-6 text-center text-sm text-gray-400" data-testid="empty-state">
            No extraction runs found.
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {runs.map((run) => (
              <li key={run._key} className="group/run relative">
                <button
                  onClick={() => onSelectRun(run._key)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                    selectedRunId === run._key
                      ? "bg-blue-50 border-l-2 border-blue-500"
                      : ""
                  }`}
                  data-testid={`run-item-${run._key}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-gray-800 truncate max-w-[180px]" title={run.document_name}>
                      {run.document_name || truncateId(run._key)}
                    </span>
                    <StatusBadge status={run.status} size="sm" />
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-gray-400">
                    <span className="font-mono" title={run._key}>
                      {truncateId(run._key)}
                    </span>
                    <span className="whitespace-nowrap ml-2">
                      {formatRelativeTime(run.started_at ?? run.created_at)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[11px] text-gray-500">
                    {run.chunk_count != null && run.chunk_count > 0 && (
                      <span title="Chunks processed">{run.chunk_count} chunks</span>
                    )}
                    {run.classes_extracted != null && run.classes_extracted > 0 && (
                      <span title="Classes extracted">{run.classes_extracted} classes</span>
                    )}
                    {run.properties_extracted != null && run.properties_extracted > 0 && (
                      <span title="Properties extracted">{run.properties_extracted} props</span>
                    )}
                    {run.error_count != null && run.error_count > 0 && (
                      <span className="text-red-500" title="Errors">{run.error_count} error{run.error_count > 1 ? "s" : ""}</span>
                    )}
                    {run.duration_ms != null && run.duration_ms > 0 && (
                      <span title="Duration">{formatDuration(run.duration_ms)}</span>
                    )}
                    {run.model && (
                      <span className="text-gray-400" title="Model">{run.model}</span>
                    )}
                  </div>
                </button>
                <button
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (!confirm(`Delete run ${run._key}?`)) return;
                    try {
                      await api.delete(`/api/v1/extraction/runs/${run._key}`);
                      setRuns((prev) => prev.filter((r) => r._key !== run._key));
                      setTotalCount((c) => Math.max(0, c - 1));
                    } catch { /* ignore */ }
                  }}
                  className="absolute top-2 right-2 hidden group-hover/run:block text-gray-300 hover:text-red-500 transition-colors p-1"
                  title="Delete run"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}

        {hasMore && (
          <div className="p-3 border-t border-gray-100">
            <button
              onClick={() => fetchRuns(true, cursor)}
              className="w-full text-sm text-blue-600 hover:text-blue-800 py-1"
            >
              Load more
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
