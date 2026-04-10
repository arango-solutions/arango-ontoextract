"use client";

import { useState, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useDraggablePanel } from "@/hooks/useDraggablePanel";
import PanelDragGrip from "@/components/workspace/PanelDragGrip";

interface FloatingDetailPanelProps {
  entityType: "class" | "edge" | "property";
  entityKey: string;
  ontologyId: string;
  onClose: () => void;
}

interface PropertyItem {
  _key: string;
  label?: string;
  description?: string;
  range?: string;
  range_datatype?: string;
  rdf_type?: string;
  confidence?: number;
  target_class?: { _key: string; label: string } | null;
}

interface ClassDetail {
  _key: string;
  label?: string;
  uri?: string;
  description?: string;
  confidence?: number;
  status?: string;
  rdf_type?: string;
  created?: number | string;
  attributes?: PropertyItem[];
  relationships?: PropertyItem[];
  legacy_properties?: PropertyItem[];
}

function formatCreated(val: number | string | undefined): string {
  if (val == null) return "";
  const ms = typeof val === "number" ? val * 1000 : new Date(val).getTime();
  const d = new Date(ms);
  return isNaN(d.getTime()) ? String(val) : d.toLocaleString();
}

const DETAIL_PANEL_WIDTH = 380;

export default function FloatingDetailPanel({
  entityType,
  entityKey,
  ontologyId,
  onClose,
}: FloatingDetailPanelProps) {
  const { panelRef, panelStyle, dragHandleProps } = useDraggablePanel(DETAIL_PANEL_WIDTH, {
    placement: "viewportTopRight",
  });
  const { className: dragHandleClassName, ...dragHandleEvents } = dragHandleProps;

  const [entity, setEntity] = useState<ClassDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchEntity() {
      setLoading(true);
      setError(null);

      try {
        if (entityType === "class") {
          const res = await api.get<ClassDetail>(
            `/api/v1/ontology/${ontologyId}/classes/${entityKey}`,
          );
          if (!cancelled) setEntity(res);
        } else {
          const collectionMap: Record<string, string> = {
            property: "properties",
            edge: "edges",
          };
          const collection = collectionMap[entityType] ?? "classes";
          const res = await api.get<{ data: ClassDetail[] }>(
            `/api/v1/ontology/${ontologyId}/${collection}`,
          );
          const match = res.data.find((e) => e._key === entityKey);
          if (!cancelled) {
            setEntity(match ?? null);
            if (!match) setError(`${entityType} "${entityKey}" not found`);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.body.message
              : `Failed to load ${entityType} details`,
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchEntity();
    return () => { cancelled = true; };
  }, [entityType, entityKey, ontologyId]);

  const typeLabel = entityType.charAt(0).toUpperCase() + entityType.slice(1);

  const attributes = entity?.attributes ?? [];
  const relationships = entity?.relationships ?? [];
  const legacyProps = entity?.legacy_properties ?? [];
  const hasProperties = attributes.length > 0 || relationships.length > 0 || legacyProps.length > 0;

  return (
    <div
      ref={panelRef}
      style={panelStyle}
      className="max-h-[80vh] bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden flex flex-col"
      role="dialog"
      aria-label={`${typeLabel} detail panel`}
    >
      {/* Header — drag handle */}
      <div
        className={`flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0 ${dragHandleClassName}`}
        {...dragHandleEvents}
      >
        <div className="flex items-center gap-2 min-w-0">
          <PanelDragGrip />
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium flex-shrink-0">
            {typeLabel}
          </span>
          <span className="text-sm font-semibold text-gray-800 truncate">
            {entity?.label ?? entityKey}
          </span>
        </div>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none ml-2 flex-shrink-0 cursor-pointer"
          aria-label="Close detail panel"
        >
          &times;
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <p className="text-sm text-gray-400 animate-pulse py-4 text-center">
            Loading {entityType} details...
          </p>
        )}

        {error && (
          <p className="text-sm text-red-500 py-4 text-center">{error}</p>
        )}

        {!loading && !error && entity && (
          <div className="space-y-4">
            {entity.uri && (
              <div>
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                  URI
                </dt>
                <dd className="text-xs text-gray-600 font-mono break-all">
                  {entity.uri}
                </dd>
              </div>
            )}

            {entity.description && (
              <div>
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                  Description
                </dt>
                <dd className="text-sm text-gray-700 leading-relaxed">
                  {entity.description}
                </dd>
              </div>
            )}

            <div className="flex gap-4 flex-wrap">
              {entity.confidence != null && (
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    Confidence
                  </dt>
                  <dd className="text-sm font-semibold text-gray-800">
                    {(entity.confidence * 100).toFixed(0)}%
                  </dd>
                </div>
              )}
              {entity.status && (
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    Status
                  </dt>
                  <dd className="text-sm text-gray-700 capitalize">{entity.status}</dd>
                </div>
              )}
              {entity.rdf_type && (
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    RDF Type
                  </dt>
                  <dd className="text-xs text-gray-600 font-mono">{entity.rdf_type}</dd>
                </div>
              )}
            </div>

            {entity.created && (
              <div>
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                  Created
                </dt>
                <dd className="text-xs text-gray-600">{formatCreated(entity.created)}</dd>
              </div>
            )}

            {entityType === "class" && !hasProperties && (
              <p className="text-xs text-gray-500 border-t border-gray-100 pt-3">
                No datatype attributes or object relationships are linked to this class yet.
                They appear when the ontology uses PGT-aligned properties (rdfs:domain edges) or
                legacy <code className="text-[10px]">has_property</code> links from extraction.
              </p>
            )}

            {/* ── Properties Section ──────────────── */}
            {entityType === "class" && hasProperties && (
              <div className="border-t border-gray-100 pt-3">
                {attributes.length > 0 && (
                  <div className="mb-3">
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                      Attributes ({attributes.length})
                    </dt>
                    <div className="space-y-1.5">
                      {attributes.map((attr) => (
                        <div
                          key={attr._key}
                          className="flex items-baseline gap-2 text-xs bg-gray-50 rounded-md px-2.5 py-1.5"
                        >
                          <span className="font-medium text-gray-800">{attr.label ?? attr._key}</span>
                          <span className="text-gray-400">:</span>
                          <span className="text-purple-600 font-mono text-[11px]">
                            {attr.range_datatype ?? attr.range ?? "—"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {relationships.length > 0 && (
                  <div className="mb-3">
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                      Relationships ({relationships.length})
                    </dt>
                    <div className="space-y-1.5">
                      {relationships.map((rel) => (
                        <div
                          key={rel._key}
                          className="flex items-baseline gap-2 text-xs bg-blue-50 rounded-md px-2.5 py-1.5"
                        >
                          <span className="font-medium text-gray-800">{rel.label ?? rel._key}</span>
                          <span className="text-gray-400">&rarr;</span>
                          <span className="text-blue-600 font-medium">
                            {rel.target_class?.label ?? "?"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {legacyProps.length > 0 && attributes.length === 0 && relationships.length === 0 && (
                  <div>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                      Properties ({legacyProps.length})
                    </dt>
                    <div className="space-y-1.5">
                      {legacyProps.map((prop) => (
                        <div
                          key={prop._key}
                          className="flex items-baseline gap-2 text-xs bg-gray-50 rounded-md px-2.5 py-1.5"
                        >
                          <span className="font-medium text-gray-800">{prop.label ?? prop._key}</span>
                          {prop.range && (
                            <>
                              <span className="text-gray-400">:</span>
                              <span className="text-purple-600 font-mono text-[11px]">{prop.range}</span>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
