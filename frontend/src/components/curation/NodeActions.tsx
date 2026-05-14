"use client";

import { useState, useCallback } from "react";
import { recordCurationDecision } from "@/lib/curationThroughput";
import type { CurationDecisionType } from "@/types/curation";

interface NodeActionsProps {
  entityKey: string;
  entityType: "class" | "property";
  runId: string;
  currentStatus: string;
  onDecision?: (key: string, decision: CurationDecisionType) => void;
}

export default function NodeActions({
  entityKey,
  entityType,
  runId,
  currentStatus,
  onDecision,
}: NodeActionsProps) {
  const [loading, setLoading] = useState<CurationDecisionType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDecision = useCallback(
    async (decision: CurationDecisionType) => {
      setLoading(decision);
      setError(null);

      onDecision?.(entityKey, decision);

      try {
        await recordCurationDecision({
          run_id: runId,
          entity_key: entityKey,
          entity_type: entityType,
          decision,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Decision failed");
        onDecision?.(entityKey, currentStatus as CurationDecisionType);
      } finally {
        setLoading(null);
      }
    },
    [entityKey, entityType, runId, currentStatus, onDecision],
  );

  return (
    <div className="space-y-2" data-testid="node-actions">
      <div className="flex gap-2">
        <button
          onClick={() => handleDecision("approve")}
          disabled={loading !== null}
          className="flex-1 flex items-center justify-center gap-1.5 text-sm px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          data-testid="approve-btn"
        >
          {loading === "approve" ? (
            <Spinner />
          ) : (
            <span>&#10003;</span>
          )}
          Approve
        </button>
        <button
          onClick={() => handleDecision("reject")}
          disabled={loading !== null}
          className="flex-1 flex items-center justify-center gap-1.5 text-sm px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          data-testid="reject-btn"
        >
          {loading === "reject" ? (
            <Spinner />
          ) : (
            <span>&#10007;</span>
          )}
          Reject
        </button>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => handleDecision("edit")}
          disabled={loading !== null}
          className="flex-1 flex items-center justify-center gap-1.5 text-sm px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          data-testid="edit-btn"
        >
          {loading === "edit" ? <Spinner /> : <span>&#9998;</span>}
          Edit
        </button>
        <button
          onClick={() => handleDecision("merge")}
          disabled={loading !== null}
          className="flex-1 flex items-center justify-center gap-1.5 text-sm px-3 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          data-testid="merge-btn"
        >
          {loading === "merge" ? <Spinner /> : <span>&#8644;</span>}
          Merge
        </button>
      </div>
      {error && (
        <p className="text-xs text-red-600 bg-red-50 px-3 py-1.5 rounded-md" data-testid="action-error">
          {error}
        </p>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      data-testid="spinner"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
