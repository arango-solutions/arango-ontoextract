"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { CurationStatus } from "@/types/curation";

export interface ClassBoxProperty {
  _key: string;
  label: string;
  range_datatype?: string;
  range?: string;
  target_class_label?: string;
  status?: CurationStatus;
}

export interface ClassBoxNodeData {
  label: string;
  uri?: string;
  status?: CurationStatus;
  confidence?: number;
  headerColor: string;
  borderColor: string;
  properties: ClassBoxProperty[];
  isSelected: boolean;
  /**
   * Effective-graph annotation (Stream 1 H.12 / H.15). When ``true`` the
   * class is owned by an imported ontology and the box renders with a
   * dashed border + reduced opacity + a small "imported" hint in the
   * header so the user sees they cannot edit it here.
   */
  isImported?: boolean;
  /** Display name of the source ontology — drives the tooltip on imported
   *  classes ("Imported from <name>"). Falls back to the source ontology
   *  id when the name is missing. */
  sourceOntologyName?: string | null;
}

const STATUS_DOT: Record<string, string> = {
  approved: "bg-green-500",
  rejected: "bg-red-400",
  pending: "bg-amber-400",
};

function ClassBoxNode({ data }: NodeProps<ClassBoxNodeData>) {
  const {
    label,
    headerColor,
    borderColor,
    properties,
    isSelected,
    status,
    isImported,
    sourceOntologyName,
  } = data;

  const maxVisible = 12;
  const visibleProps = properties.slice(0, maxVisible);
  const overflow = properties.length - maxVisible;

  const importedTitle = isImported
    ? `Imported from ${sourceOntologyName ?? "another ontology"}`
    : undefined;

  return (
    <div
      className={`rounded-lg shadow-md min-w-[180px] max-w-[260px] overflow-hidden transition-shadow ${
        isSelected ? "ring-2 ring-indigo-400 shadow-indigo-400/30" : ""
      } ${isImported ? "opacity-75" : ""}`}
      style={{
        borderWidth: 2,
        borderStyle: isImported ? "dashed" : "solid",
        borderColor,
      }}
      title={importedTitle}
      data-imported={isImported ? "true" : undefined}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 !w-2 !h-2" />

      {/* Header */}
      <div
        className="px-3 py-1.5 flex items-center gap-1.5"
        style={{ backgroundColor: headerColor }}
      >
        {status && STATUS_DOT[status] && (
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]}`}
            title={status}
          />
        )}
        <span className="text-xs font-semibold text-white truncate drop-shadow-sm">
          {label}
        </span>
        {isImported && (
          <span
            className="ml-auto text-[9px] uppercase tracking-wide text-white/90 flex-shrink-0"
            title={importedTitle}
            aria-label={importedTitle}
          >
            imported
          </span>
        )}
      </div>

      {/* Properties */}
      {visibleProps.length > 0 && (
        <div className="bg-gray-900/80 divide-y divide-gray-700/50">
          {visibleProps.map((prop) => {
            const rangeLabel = prop.target_class_label
              ?? prop.range_datatype
              ?? prop.range
              ?? "";
            return (
              <div
                key={prop._key}
                className="px-3 py-0.5 text-[10px] flex items-center gap-1 text-gray-300 hover:bg-gray-800/50 transition-colors"
                title={`${prop.label}: ${rangeLabel}`}
              >
                <span className="truncate flex-1">{prop.label}</span>
                {rangeLabel && (
                  <span className="text-gray-500 truncate max-w-[80px] text-[9px]">
                    {rangeLabel}
                  </span>
                )}
              </div>
            );
          })}
          {overflow > 0 && (
            <div className="px-3 py-0.5 text-[9px] text-gray-500 italic">
              +{overflow} more
            </div>
          )}
        </div>
      )}

      {visibleProps.length === 0 && (
        <div className="bg-gray-900/80 px-3 py-1 text-[10px] text-gray-500 italic">
          No properties
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}

export default memo(ClassBoxNode);
