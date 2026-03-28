"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api-client";
import type { StepStatus } from "@/types/pipeline";
import { STEP_LABELS, type PipelineStep } from "@/types/pipeline";

interface ErrorLogProps {
  steps: Map<string, StepStatus>;
  runId: string | null;
}

interface ErrorEntry {
  stepKey: string;
  stepLabel: string;
  error: string;
  timestamp: string;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function ErrorLog({ steps, runId }: ErrorLogProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryResult, setRetryResult] = useState<string | null>(null);

  const errors: ErrorEntry[] = [];
  steps.forEach((step, key) => {
    if (step.status === "failed" && step.error) {
      errors.push({
        stepKey: key,
        stepLabel:
          STEP_LABELS[key as PipelineStep] ?? key,
        error: step.error,
        timestamp: step.completedAt ?? step.startedAt ?? "",
      });
    }
  });

  const handleRetry = useCallback(async () => {
    if (!runId) return;
    setRetrying(true);
    setRetryResult(null);
    try {
      await api.post(`/api/v1/extraction/runs/${runId}/retry`);
      setRetryResult("Retry triggered successfully.");
    } catch (err) {
      setRetryResult(
        err instanceof Error ? err.message : "Retry failed.",
      );
    } finally {
      setRetrying(false);
    }
  }, [runId]);

  if (errors.length === 0) {
    return (
      <div className="p-4 text-sm text-gray-400" data-testid="error-log-empty">
        No errors recorded.
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3" data-testid="error-log">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Errors ({errors.length})
        </h3>
        {runId && (
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="text-sm px-3 py-1 rounded-lg bg-red-50 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
            data-testid="retry-button"
          >
            {retrying ? "Retrying\u2026" : "Retry Run"}
          </button>
        )}
      </div>

      {retryResult && (
        <div
          className={`text-xs px-3 py-2 rounded-lg ${retryResult.includes("success") ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}
          data-testid="retry-result"
        >
          {retryResult}
        </div>
      )}

      <ul className="space-y-2">
        {errors.map((entry, idx) => (
          <li
            key={`${entry.stepKey}-${idx}`}
            className="bg-red-50 border border-red-200 rounded-lg overflow-hidden"
          >
            <button
              onClick={() =>
                setExpandedIdx(expandedIdx === idx ? null : idx)
              }
              className="w-full text-left px-4 py-3 hover:bg-red-100 transition-colors"
              data-testid={`error-entry-${idx}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-red-400 font-mono">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                  <span className="text-sm font-semibold text-red-800">
                    {entry.stepLabel}
                  </span>
                </div>
                <span className="text-xs text-red-400">
                  {expandedIdx === idx ? "\u25B2" : "\u25BC"}
                </span>
              </div>
              <p className="text-sm text-red-700 mt-1 truncate">
                {entry.error}
              </p>
            </button>

            {expandedIdx === idx && (
              <div className="px-4 pb-3 border-t border-red-200">
                <pre className="text-xs text-red-600 whitespace-pre-wrap mt-2 font-mono bg-red-100/50 p-2 rounded max-h-48 overflow-y-auto">
                  {entry.error}
                </pre>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
