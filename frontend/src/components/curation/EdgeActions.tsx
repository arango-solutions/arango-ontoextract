"use client";

import { useState, useCallback } from "react";
import { recordCurationDecision } from "@/lib/curationThroughput";
import type { EdgeType, CurationDecisionType } from "@/types/curation";

interface EdgeActionsProps {
  edgeKey: string;
  runId: string;
  currentType: EdgeType;
  currentLabel: string;
  onDecision?: (key: string, decision: CurationDecisionType) => void;
  onTypeChange?: (key: string, newType: EdgeType) => void;
}

const EDGE_TYPE_OPTIONS: { value: EdgeType; label: string }[] = [
  { value: "subclass_of", label: "Subclass Of" },
  { value: "equivalent_class", label: "Equivalent Class" },
  { value: "has_property", label: "Has Property" },
  { value: "extends_domain", label: "Extends Domain" },
  { value: "related_to", label: "Related To" },
  { value: "extracted_from", label: "Extracted From" },
  { value: "imports", label: "Imports" },
];

export default function EdgeActions({
  edgeKey,
  runId,
  currentType,
  currentLabel,
  onDecision,
  onTypeChange,
}: EdgeActionsProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<EdgeType>(currentType);

  const handleDecision = useCallback(
    async (decision: CurationDecisionType) => {
      setLoading(decision);
      setError(null);
      onDecision?.(edgeKey, decision);

      try {
        await recordCurationDecision({
          run_id: runId,
          entity_key: edgeKey,
          entity_type: "edge",
          decision,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Action failed");
      } finally {
        setLoading(null);
      }
    },
    [edgeKey, runId, onDecision],
  );

  const handleChangeType = useCallback(async () => {
    if (selectedType === currentType) return;
    setLoading("change_type");
    setError(null);
    onTypeChange?.(edgeKey, selectedType);

    try {
      await recordCurationDecision({
        run_id: runId,
        entity_key: edgeKey,
        entity_type: "edge",
        decision: "edit",
        after_state: { type: selectedType },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Type change failed");
      setSelectedType(currentType);
    } finally {
      setLoading(null);
    }
  }, [edgeKey, runId, currentType, selectedType, onTypeChange]);

  return (
    <div className="space-y-3" data-testid="edge-actions">
      <div>
        <h4 className="text-sm font-semibold text-gray-800 mb-1">Edge: {currentLabel}</h4>
        <span className="text-xs text-gray-500 bg-gray-50 px-2 py-0.5 rounded-full">
          {currentType.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => handleDecision("approve")}
          disabled={loading !== null}
          className="flex-1 text-sm px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
          data-testid="edge-approve-btn"
        >
          {loading === "approve" ? "..." : "Approve"}
        </button>
        <button
          onClick={() => handleDecision("reject")}
          disabled={loading !== null}
          className="flex-1 text-sm px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
          data-testid="edge-reject-btn"
        >
          {loading === "reject" ? "..." : "Reject"}
        </button>
      </div>

      <div>
        <label className="text-xs font-medium text-gray-600 block mb-1">
          Change Type
        </label>
        <div className="flex gap-2">
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value as EdgeType)}
            className="flex-1 text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:ring-2 focus:ring-blue-500"
            data-testid="edge-type-select"
          >
            {EDGE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            onClick={handleChangeType}
            disabled={loading !== null || selectedType === currentType}
            className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            data-testid="edge-change-type-btn"
          >
            {loading === "change_type" ? "..." : "Apply"}
          </button>
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 px-3 py-1.5 rounded-md" data-testid="edge-action-error">
          {error}
        </p>
      )}
    </div>
  );
}
