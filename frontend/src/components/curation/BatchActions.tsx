"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api-client";
import type { CurationDecisionType } from "@/types/curation";

interface BatchActionsProps {
  selectedKeys: string[];
  entityType: "class" | "property" | "edge";
  runId: string;
  onBatchDecision?: (keys: string[], decision: CurationDecisionType) => void;
  onClearSelection?: () => void;
}

export default function BatchActions({
  selectedKeys,
  entityType,
  runId,
  onBatchDecision,
  onClearSelection,
}: BatchActionsProps) {
  const [loading, setLoading] = useState<CurationDecisionType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleBatch = useCallback(
    async (decision: CurationDecisionType) => {
      if (selectedKeys.length === 0) return;
      setLoading(decision);
      setError(null);

      onBatchDecision?.(selectedKeys, decision);

      try {
        await api.post("/api/v1/curation/batch", {
          run_id: runId,
          decisions: selectedKeys.map((key) => ({
            entity_key: key,
            entity_type: entityType,
            action: decision,
            curator_id: "anonymous",
          })),
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Batch operation failed");
      } finally {
        setLoading(null);
      }
    },
    [selectedKeys, entityType, runId, onBatchDecision],
  );

  if (selectedKeys.length === 0) return null;

  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-white border border-gray-200 rounded-xl shadow-lg px-6 py-3 flex items-center gap-4"
      data-testid="batch-actions"
    >
      <span className="text-sm font-medium text-gray-700">
        <span className="text-blue-600 font-bold" data-testid="batch-count">
          {selectedKeys.length}
        </span>{" "}
        item{selectedKeys.length !== 1 ? "s" : ""} selected
      </span>

      <div className="h-5 w-px bg-gray-200" />

      <button
        onClick={() => handleBatch("approve")}
        disabled={loading !== null}
        className="flex items-center gap-1.5 text-sm px-4 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
        data-testid="batch-approve-btn"
      >
        {loading === "approve" ? "..." : "Approve All"}
      </button>

      <button
        onClick={() => handleBatch("reject")}
        disabled={loading !== null}
        className="flex items-center gap-1.5 text-sm px-4 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
        data-testid="batch-reject-btn"
      >
        {loading === "reject" ? "..." : "Reject All"}
      </button>

      <div className="h-5 w-px bg-gray-200" />

      <button
        onClick={onClearSelection}
        className="text-sm text-gray-500 hover:text-gray-700"
        data-testid="batch-clear-btn"
      >
        Clear
      </button>

      {error && (
        <span className="text-xs text-red-600" data-testid="batch-error">
          {error}
        </span>
      )}
    </div>
  );
}
