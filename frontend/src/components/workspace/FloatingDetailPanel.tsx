"use client";

import { useState, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

interface FloatingDetailPanelProps {
  entityType: "class" | "edge" | "property";
  entityKey: string;
  ontologyId: string;
  onClose: () => void;
}

interface EntityDetail {
  _key: string;
  label?: string;
  uri?: string;
  description?: string;
  confidence?: number;
  status?: string;
  rdf_type?: string;
  created?: string;
}

export default function FloatingDetailPanel({
  entityType,
  entityKey,
  ontologyId,
  onClose,
}: FloatingDetailPanelProps) {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchEntity() {
      setLoading(true);
      setError(null);

      const collectionMap: Record<string, string> = {
        class: "classes",
        property: "properties",
        edge: "edges",
      };
      const collection = collectionMap[entityType] ?? "classes";

      try {
        const res = await api.get<{ data: EntityDetail[] }>(
          `/api/v1/ontology/${ontologyId}/${collection}`,
        );
        const match = res.data.find((e) => e._key === entityKey);
        if (!cancelled) {
          setEntity(match ?? null);
          if (!match) setError(`${entityType} "${entityKey}" not found`);
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
    return () => {
      cancelled = true;
    };
  }, [entityType, entityKey, ontologyId]);

  const typeLabel = entityType.charAt(0).toUpperCase() + entityType.slice(1);

  return (
    <div
      className="absolute top-4 right-4 w-[360px] max-h-[70vh] bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden flex flex-col z-50"
      role="dialog"
      aria-label={`${typeLabel} detail panel`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium flex-shrink-0">
            {typeLabel}
          </span>
          <span className="text-sm font-semibold text-gray-800 truncate">
            {entity?.label ?? entityKey}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none ml-2 flex-shrink-0"
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

            <div className="flex gap-4">
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
                  <dd className="text-sm text-gray-700 capitalize">
                    {entity.status}
                  </dd>
                </div>
              )}

              {entity.rdf_type && (
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    RDF Type
                  </dt>
                  <dd className="text-xs text-gray-600 font-mono">
                    {entity.rdf_type}
                  </dd>
                </div>
              )}
            </div>

            {entity.created && (
              <div>
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                  Created
                </dt>
                <dd className="text-xs text-gray-600">
                  {new Date(entity.created).toLocaleString()}
                </dd>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
