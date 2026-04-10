"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import { splitTextByKeywordAlternation } from "@/lib/textHighlight";
import type { SourceChunk } from "@/types/curation";

interface ProvenancePanelProps {
  entityKey: string;
  entityLabel: string;
  onClose?: () => void;
}

interface ChunkResponse {
  data: SourceChunk[];
  total_count: number;
}

function highlightKeywords(text: string, keywords: string[]): JSX.Element {
  if (keywords.length === 0) return <>{text}</>;
  const parts = splitTextByKeywordAlternation(text, keywords);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="bg-yellow-200 rounded px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export default function ProvenancePanel({
  entityKey,
  entityLabel,
  onClose,
}: ProvenancePanelProps) {
  const [chunks, setChunks] = useState<SourceChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const keywords = entityLabel
    .split(/[\s_-]+/)
    .filter((w) => w.length > 2);

  const fetchChunks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<ChunkResponse>(
        `/api/v1/ontology/class/${entityKey}/provenance`,
      );
      setChunks(res.data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load provenance data",
      );
    } finally {
      setLoading(false);
    }
  }, [entityKey]);

  useEffect(() => {
    fetchChunks();
  }, [fetchChunks]);

  return (
    <div className="space-y-3" data-testid="provenance-panel">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">
          Source Provenance
        </h3>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="Close provenance"
          >
            &times;
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500">
        Showing document chunks that contributed to{" "}
        <span className="font-medium text-gray-700">{entityLabel}</span>
      </p>
      <p className="text-[11px] leading-snug text-gray-600 bg-gray-100 border border-gray-200 rounded-md px-2 py-1.5">
        Each class is linked to <span className="font-medium">whole source documents</span>, not a
        specific substring. Listed chunks are from those documents; yellow highlights match the class
        name (and long words) heuristically — we do not store character offsets from extraction.
      </p>

      {loading && (
        <div className="py-6 text-center text-sm text-gray-400 animate-pulse" data-testid="provenance-loading">
          Loading provenance...
        </div>
      )}

      {error && (
        <div className="py-3 px-3 text-sm text-red-600 bg-red-50 rounded-lg" data-testid="provenance-error">
          {error}
        </div>
      )}

      {!loading && !error && chunks.length === 0 && (
        <div className="py-6 text-center text-sm text-gray-400" data-testid="provenance-empty">
          No source chunks found for this entity.
        </div>
      )}

      {!loading && chunks.length > 0 && (
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {chunks.map((chunk) => (
            <div
              key={chunk._key}
              className="bg-gray-50 rounded-lg border border-gray-100 p-3"
              data-testid={`chunk-${chunk._key}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-xs font-medium text-gray-700">
                  {chunk.document_name}
                </span>
                {chunk.page != null && (
                  <span className="text-xs text-gray-400">
                    Page {chunk.page}
                  </span>
                )}
                {chunk.section && (
                  <span className="text-xs text-gray-400">
                    &middot; {chunk.section}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-600 leading-relaxed">
                {highlightKeywords(chunk.text, keywords)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
