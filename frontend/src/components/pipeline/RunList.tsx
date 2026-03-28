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

function formatRelativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
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
              <li key={run._key}>
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
                    <span
                      className="text-sm font-mono text-gray-700"
                      title={run._key}
                    >
                      {truncateId(run._key)}
                    </span>
                    <StatusBadge status={run.status} size="sm" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-500 truncate max-w-[160px]">
                      {run.document_name}
                    </span>
                    <span className="text-xs text-gray-400 whitespace-nowrap ml-2">
                      {formatRelativeTime(run.created_at)}
                    </span>
                  </div>
                  {run.duration_ms !== undefined && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      Duration: {formatDuration(run.duration_ms)}
                    </div>
                  )}
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
