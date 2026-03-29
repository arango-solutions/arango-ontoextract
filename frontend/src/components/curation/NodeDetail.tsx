"use client";

import { useState, useCallback } from "react";
import type { OntologyClass } from "@/types/curation";

interface NodeDetailProps {
  node: OntologyClass;
  onDescriptionChange?: (key: string, description: string) => void;
  onShowProvenance?: (key: string) => void;
  onShowHistory?: (key: string) => void;
}

function confidenceBarColor(confidence: number): string {
  if (confidence >= 0.8) return "bg-green-500";
  if (confidence >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

function confidenceLabel(confidence: number): string {
  if (confidence >= 0.8) return "High";
  if (confidence >= 0.5) return "Medium";
  return "Low";
}

export default function NodeDetail({
  node,
  onDescriptionChange,
  onShowProvenance,
  onShowHistory,
}: NodeDetailProps) {
  const [editingDescription, setEditingDescription] = useState(false);
  const [draftDescription, setDraftDescription] = useState(node.description);

  const handleSaveDescription = useCallback(() => {
    onDescriptionChange?.(node._key, draftDescription);
    setEditingDescription(false);
  }, [node._key, draftDescription, onDescriptionChange]);

  const handleCancelEdit = useCallback(() => {
    setDraftDescription(node.description);
    setEditingDescription(false);
  }, [node.description]);

  return (
    <div className="space-y-4" data-testid="node-detail">
      {/* Header */}
      <div>
        <h3 className="text-base font-semibold text-gray-900">{node.label}</h3>
        <p className="text-xs text-gray-400 font-mono mt-0.5 break-all">
          {node.uri}
        </p>
      </div>

      {/* Status + Type */}
      <div className="flex items-center gap-2">
        <span
          className={`text-xs font-medium px-2 py-0.5 rounded-full ${
            node.status === "approved"
              ? "bg-green-50 text-green-700"
              : node.status === "rejected"
                ? "bg-red-50 text-red-700"
                : "bg-gray-100 text-gray-700"
          }`}
          data-testid="node-status-badge"
        >
          {(node.status ?? "pending").charAt(0).toUpperCase() + (node.status ?? "pending").slice(1)}
        </span>
        <span className="text-xs text-gray-500 bg-gray-50 px-2 py-0.5 rounded-full">
          {node.rdf_type}
        </span>
      </div>

      {/* Confidence */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-gray-600">Confidence</span>
          <span className="text-xs text-gray-500">
            {(node.confidence * 100).toFixed(0)}% — {confidenceLabel(node.confidence)}
          </span>
        </div>
        <div
          className="h-2 bg-gray-200 rounded-full overflow-hidden"
          data-testid="confidence-bar"
        >
          <div
            className={`h-full rounded-full transition-all ${confidenceBarColor(node.confidence)}`}
            style={{ width: `${node.confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Description */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-gray-600">Description</span>
          {!editingDescription && (
            <button
              onClick={() => setEditingDescription(true)}
              className="text-xs text-blue-600 hover:text-blue-800"
              data-testid="edit-description-btn"
            >
              Edit
            </button>
          )}
        </div>
        {editingDescription ? (
          <div className="space-y-2">
            <textarea
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              className="w-full text-sm border border-gray-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-y min-h-[60px]"
              data-testid="description-textarea"
            />
            <div className="flex gap-2">
              <button
                onClick={handleSaveDescription}
                className="text-xs px-3 py-1 bg-blue-600 text-white rounded-md hover:bg-blue-700"
                data-testid="save-description-btn"
              >
                Save
              </button>
              <button
                onClick={handleCancelEdit}
                className="text-xs px-3 py-1 border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-700">
            {node.description || "No description available."}
          </p>
        )}
      </div>

      {/* Metadata */}
      <div className="space-y-2 pt-2 border-t border-gray-100">
        <div className="flex justify-between text-xs">
          <span className="text-gray-500">Ontology ID</span>
          <span className="text-gray-700 font-mono">{node.ontology_id}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-500">Created</span>
          <span className="text-gray-700">
            {node.created
              ? new Date(typeof node.created === "number" ? node.created * 1000 : node.created).toLocaleString()
              : "—"}
          </span>
        </div>
        {node.expired != null && node.expired !== 9223372036854775807 && (
          <div className="flex justify-between text-xs">
            <span className="text-gray-500">Expired</span>
            <span className="text-gray-700">
              {new Date(typeof node.expired === "number" ? node.expired * 1000 : node.expired).toLocaleString()}
            </span>
          </div>
        )}
      </div>

      {/* Links */}
      <div className="flex gap-2 pt-2 border-t border-gray-100">
        <button
          onClick={() => onShowProvenance?.(node._key)}
          className="flex-1 text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50"
          data-testid="show-provenance-btn"
        >
          View Provenance
        </button>
        <button
          onClick={() => onShowHistory?.(node._key)}
          className="flex-1 text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50"
          data-testid="show-history-btn"
        >
          History
        </button>
      </div>
    </div>
  );
}
