"use client";

import { useState, useCallback, useMemo } from "react";
import { api, ApiError } from "@/lib/api-client";
import type {
  MergeCandidate,
  EntityDetail,
  MergeResult,
} from "@/types/entity-resolution";

interface MergeExecutorProps {
  candidate: MergeCandidate;
  entityLeft: EntityDetail | null;
  entityRight: EntityDetail | null;
  loading: boolean;
  onMerged?: (result: MergeResult) => void;
  onClose?: () => void;
}

type FieldChoice = "left" | "right" | "custom";

interface FieldSelection {
  label: { choice: FieldChoice; custom: string };
  description: { choice: FieldChoice; custom: string };
  uri: { choice: FieldChoice; custom: string };
}

function initFieldSelection(
  left: EntityDetail | null,
  right: EntityDetail | null,
): FieldSelection {
  return {
    label: { choice: "left", custom: left?.label ?? "" },
    description: { choice: "left", custom: left?.description ?? "" },
    uri: { choice: "left", custom: left?.uri ?? "" },
  };
}

function resolveFieldValue(
  field: keyof FieldSelection,
  selection: FieldSelection,
  left: EntityDetail | null,
  right: EntityDetail | null,
): string {
  const sel = selection[field];
  if (sel.choice === "custom") return sel.custom;
  if (sel.choice === "right") return right?.[field] ?? "";
  return left?.[field] ?? "";
}

export default function MergeExecutor({
  candidate,
  entityLeft,
  entityRight,
  loading: entitiesLoading,
  onMerged,
  onClose,
}: MergeExecutorProps) {
  const [fieldSelection, setFieldSelection] = useState<FieldSelection>(() =>
    initFieldSelection(entityLeft, entityRight),
  );
  const [propertySelections, setPropertySelections] = useState<
    Record<string, "left" | "right">
  >({});
  const [merging, setMerging] = useState(false);
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [mergeResult, setMergeResult] = useState<MergeResult | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const allPropertyKeys = useMemo(() => {
    const keys = new Set<string>();
    if (entityLeft?.properties) {
      Object.keys(entityLeft.properties).forEach((k) => keys.add(k));
    }
    if (entityRight?.properties) {
      Object.keys(entityRight.properties).forEach((k) => keys.add(k));
    }
    return Array.from(keys).sort();
  }, [entityLeft, entityRight]);

  const mergedProperties = useMemo(() => {
    const props: Record<string, string> = {};
    for (const key of allPropertyKeys) {
      const choice = propertySelections[key] ?? "left";
      const leftVal = entityLeft?.properties?.[key] ?? "";
      const rightVal = entityRight?.properties?.[key] ?? "";
      props[key] = choice === "right" ? rightVal : leftVal || rightVal;
    }
    return props;
  }, [allPropertyKeys, propertySelections, entityLeft, entityRight]);

  const mergedPreview = useMemo(
    () => ({
      label: resolveFieldValue("label", fieldSelection, entityLeft, entityRight),
      description: resolveFieldValue(
        "description",
        fieldSelection,
        entityLeft,
        entityRight,
      ),
      uri: resolveFieldValue("uri", fieldSelection, entityLeft, entityRight),
      properties: mergedProperties,
    }),
    [fieldSelection, entityLeft, entityRight, mergedProperties],
  );

  const updateField = useCallback(
    (field: keyof FieldSelection, choice: FieldChoice, custom?: string) => {
      setFieldSelection((prev) => ({
        ...prev,
        [field]: {
          choice,
          custom: custom ?? prev[field].custom,
        },
      }));
    },
    [],
  );

  const handleMerge = useCallback(async () => {
    setMerging(true);
    setMergeError(null);
    try {
      const result = await api.post<MergeResult>("/api/v1/er/merge", {
        pair_id: candidate.pair_id,
        golden_record: mergedPreview,
        surviving_entity_key: entityLeft?.key ?? candidate.entity_1.key,
      });
      setMergeResult(result);
      onMerged?.(result);
    } catch (err) {
      setMergeError(
        err instanceof ApiError ? err.body.message : "Merge failed",
      );
    } finally {
      setMerging(false);
    }
  }, [candidate, mergedPreview, entityLeft, onMerged]);

  if (entitiesLoading) {
    return (
      <div
        className="flex items-center justify-center h-full p-8"
        data-testid="merge-executor-loading"
      >
        <p className="text-sm text-gray-400 animate-pulse">
          Loading entity details...
        </p>
      </div>
    );
  }

  if (mergeResult) {
    return (
      <div
        className="p-6 space-y-4"
        data-testid="merge-executor-result"
      >
        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full bg-green-500" />
          <h2 className="text-base font-semibold text-gray-900">
            Merge Complete
          </h2>
        </div>

        <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Merged entity</span>
            <span className="font-medium text-gray-900">
              {mergeResult.merged_label}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Deprecated entities</span>
            <span className="font-mono text-xs text-gray-700">
              {mergeResult.deprecated_keys.join(", ")}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Edges transferred</span>
            <span className="font-medium text-gray-900">
              {mergeResult.edges_transferred}
            </span>
          </div>
        </div>

        <div className="pt-2 border-t border-gray-100">
          <p className="text-xs text-gray-500">
            Source entities preserved as provenance of the merged record.
          </p>
        </div>

        {onClose && (
          <button
            onClick={onClose}
            className="w-full text-sm px-4 py-2 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
          >
            Done
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full" data-testid="merge-executor">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">
          Merge Entities
        </h2>
        {onClose && (
          <button
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            &#10005;
          </button>
        )}
      </div>

      {/* Side-by-side comparison */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Core fields */}
        {(["label", "description", "uri"] as const).map((field) => (
          <FieldComparisonRow
            key={field}
            field={field}
            leftValue={entityLeft?.[field] ?? ""}
            rightValue={entityRight?.[field] ?? ""}
            selection={fieldSelection[field]}
            onChange={(choice, custom) => updateField(field, choice, custom)}
          />
        ))}

        {/* Properties */}
        {allPropertyKeys.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-700 mb-2 uppercase tracking-wider">
              Properties
            </h3>
            <div className="space-y-2">
              {allPropertyKeys.map((propKey) => {
                const leftVal = entityLeft?.properties?.[propKey] ?? "";
                const rightVal = entityRight?.properties?.[propKey] ?? "";
                const choice = propertySelections[propKey] ?? "left";
                return (
                  <div
                    key={propKey}
                    className="grid grid-cols-[1fr,auto,1fr] gap-2 items-center"
                  >
                    <button
                      onClick={() =>
                        setPropertySelections((prev) => ({
                          ...prev,
                          [propKey]: "left",
                        }))
                      }
                      className={`text-xs p-2 rounded border text-left truncate ${
                        choice === "left"
                          ? "border-blue-400 bg-blue-50"
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <span className="block text-[10px] text-gray-400 mb-0.5">
                        {propKey}
                      </span>
                      {leftVal || <span className="text-gray-300">—</span>}
                    </button>
                    <span className="text-xs text-gray-400">&#8596;</span>
                    <button
                      onClick={() =>
                        setPropertySelections((prev) => ({
                          ...prev,
                          [propKey]: "right",
                        }))
                      }
                      className={`text-xs p-2 rounded border text-left truncate ${
                        choice === "right"
                          ? "border-blue-400 bg-blue-50"
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <span className="block text-[10px] text-gray-400 mb-0.5">
                        {propKey}
                      </span>
                      {rightVal || <span className="text-gray-300">—</span>}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Edge summary */}
        {(entityLeft?.edges?.length || entityRight?.edges?.length) && (
          <div>
            <h3 className="text-xs font-semibold text-gray-700 mb-2 uppercase tracking-wider">
              Edges (will be transferred to merged entity)
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <EdgeList
                label={candidate.entity_1.label}
                edges={entityLeft?.edges ?? []}
              />
              <EdgeList
                label={candidate.entity_2.label}
                edges={entityRight?.edges ?? []}
              />
            </div>
          </div>
        )}

        {/* Preview toggle */}
        <button
          onClick={() => setShowPreview(!showPreview)}
          className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
          data-testid="toggle-preview-btn"
        >
          {showPreview ? "Hide Preview" : "Show Merged Preview"}
        </button>

        {showPreview && (
          <div
            className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-2"
            data-testid="merge-preview"
          >
            <h4 className="text-xs font-semibold text-blue-800">
              Merged Entity Preview
            </h4>
            <div className="space-y-1 text-sm">
              <div>
                <span className="text-xs text-gray-500">Label: </span>
                <span className="text-gray-900">{mergedPreview.label}</span>
              </div>
              <div>
                <span className="text-xs text-gray-500">URI: </span>
                <span className="text-gray-700 font-mono text-xs">
                  {mergedPreview.uri}
                </span>
              </div>
              <div>
                <span className="text-xs text-gray-500">Description: </span>
                <span className="text-gray-700">
                  {mergedPreview.description}
                </span>
              </div>
              {Object.keys(mergedPreview.properties).length > 0 && (
                <div className="pt-1 border-t border-blue-100">
                  <span className="text-xs text-gray-500">Properties: </span>
                  <ul className="text-xs text-gray-600 mt-1 space-y-0.5">
                    {Object.entries(mergedPreview.properties).map(
                      ([k, v]) => (
                        <li key={k}>
                          <span className="font-medium">{k}:</span> {v}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error */}
        {mergeError && (
          <div
            className="bg-red-50 border border-red-200 rounded-lg p-3"
            data-testid="merge-error"
          >
            <p className="text-sm text-red-600">{mergeError}</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-200 bg-white">
        <button
          onClick={handleMerge}
          disabled={merging}
          className="w-full text-sm px-4 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          data-testid="execute-merge-btn"
        >
          {merging ? "Merging..." : "Execute Merge"}
        </button>
      </div>
    </div>
  );
}

// --- Field Comparison Row ---

interface FieldComparisonRowProps {
  field: string;
  leftValue: string;
  rightValue: string;
  selection: { choice: FieldChoice; custom: string };
  onChange: (choice: FieldChoice, custom?: string) => void;
}

function FieldComparisonRow({
  field,
  leftValue,
  rightValue,
  selection,
  onChange,
}: FieldComparisonRowProps) {
  const fieldLabel = field.charAt(0).toUpperCase() + field.slice(1);

  return (
    <div data-testid={`field-comparison-${field}`}>
      <h3 className="text-xs font-semibold text-gray-700 mb-1.5 uppercase tracking-wider">
        {fieldLabel}
      </h3>
      <div className="grid grid-cols-[1fr,auto,1fr] gap-2 items-start">
        {/* Left entity */}
        <button
          onClick={() => onChange("left")}
          className={`text-xs p-3 rounded-lg border text-left ${
            selection.choice === "left"
              ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200"
              : "border-gray-200 hover:border-gray-300"
          }`}
          data-testid={`select-left-${field}`}
        >
          <span className="block text-[10px] text-gray-400 mb-0.5">
            Entity 1
          </span>
          <span className="text-gray-800 break-words">
            {leftValue || <span className="text-gray-300">—</span>}
          </span>
        </button>

        <div className="flex flex-col items-center gap-1 pt-3">
          <span className="text-xs text-gray-400">or</span>
          <button
            onClick={() => onChange("custom")}
            className={`text-[10px] px-1.5 py-0.5 rounded border ${
              selection.choice === "custom"
                ? "border-blue-400 bg-blue-50 text-blue-700"
                : "border-gray-200 text-gray-400 hover:border-gray-300"
            }`}
          >
            Custom
          </button>
        </div>

        {/* Right entity */}
        <button
          onClick={() => onChange("right")}
          className={`text-xs p-3 rounded-lg border text-left ${
            selection.choice === "right"
              ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200"
              : "border-gray-200 hover:border-gray-300"
          }`}
          data-testid={`select-right-${field}`}
        >
          <span className="block text-[10px] text-gray-400 mb-0.5">
            Entity 2
          </span>
          <span className="text-gray-800 break-words">
            {rightValue || <span className="text-gray-300">—</span>}
          </span>
        </button>
      </div>

      {/* Custom input */}
      {selection.choice === "custom" && (
        <div className="mt-2">
          {field === "description" ? (
            <textarea
              value={selection.custom}
              onChange={(e) => onChange("custom", e.target.value)}
              className="w-full text-xs border border-blue-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-y min-h-[40px]"
              data-testid={`custom-input-${field}`}
            />
          ) : (
            <input
              type="text"
              value={selection.custom}
              onChange={(e) => onChange("custom", e.target.value)}
              className="w-full text-xs border border-blue-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              data-testid={`custom-input-${field}`}
            />
          )}
        </div>
      )}
    </div>
  );
}

// --- Edge List ---

function EdgeList({
  label,
  edges,
}: {
  label: string;
  edges: { type: string; target_label: string; target_key: string }[];
}) {
  return (
    <div className="bg-gray-50 rounded-lg p-2">
      <span className="text-[10px] text-gray-400 block mb-1">{label}</span>
      {edges.length === 0 ? (
        <span className="text-xs text-gray-300">No edges</span>
      ) : (
        <ul className="space-y-0.5">
          {edges.map((e, i) => (
            <li
              key={`${e.target_key}-${i}`}
              className="text-xs text-gray-600 truncate"
            >
              <span className="text-gray-400">{e.type}</span>{" "}
              &#8594; {e.target_label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
