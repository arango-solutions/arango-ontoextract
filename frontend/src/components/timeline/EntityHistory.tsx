"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { VersionHistory, VersionEntry } from "@/types/timeline";

interface EntityHistoryProps {
  classKey: string;
  onClose?: () => void;
  onRevert?: (classKey: string, versionNumber: number) => void;
}

function diffFields(
  prev: Record<string, unknown>,
  curr: Record<string, unknown>,
): string[] {
  const keys = new Set([...Object.keys(prev), ...Object.keys(curr)]);
  const changed: string[] = [];
  for (const key of keys) {
    if (JSON.stringify(prev[key]) !== JSON.stringify(curr[key])) {
      changed.push(key);
    }
  }
  return changed;
}

function VersionCard({
  version,
  prevVersion,
  isLatest,
  onRevert,
}: {
  version: VersionEntry;
  prevVersion?: VersionEntry;
  isLatest: boolean;
  onRevert?: () => void;
}) {
  const changes = prevVersion
    ? diffFields(prevVersion.data, version.data)
    : [];

  return (
    <div
      className={`relative pl-6 pb-6 ${isLatest ? "" : "border-l-2 border-gray-200"}`}
      data-testid={`version-${version.version_number}`}
    >
      {/* Timeline dot */}
      <div
        className={`absolute left-[-5px] top-1 w-2.5 h-2.5 rounded-full border-2 ${
          isLatest
            ? "bg-blue-500 border-blue-500"
            : version.expired
              ? "bg-gray-300 border-gray-300"
              : "bg-green-500 border-green-500"
        }`}
      />

      <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-gray-700">
              v{version.version_number}
            </span>
            {isLatest && (
              <span className="text-xs bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded-full">
                Current
              </span>
            )}
          </div>
          <span className="text-xs text-gray-400">
            {new Date(version.created).toLocaleString()}
          </span>
        </div>

        {/* Changed fields */}
        {changes.length > 0 && (
          <div className="mb-2">
            <span className="text-xs text-gray-500">Changed: </span>
            {changes.map((field) => (
              <span
                key={field}
                className="inline-block text-xs bg-yellow-50 text-yellow-700 px-1.5 py-0.5 rounded mr-1 mb-0.5"
              >
                {field}
              </span>
            ))}
          </div>
        )}

        {/* Key fields */}
        <div className="space-y-1 text-xs text-gray-600">
          {version.data.label != null && (
            <div>
              <span className="text-gray-400">Label: </span>
              <span className="font-medium">{String(version.data.label)}</span>
            </div>
          )}
          {version.data.description != null && (
            <div>
              <span className="text-gray-400">Description: </span>
              <span>{String(version.data.description)}</span>
            </div>
          )}
          {version.data.confidence != null && (
            <div>
              <span className="text-gray-400">Confidence: </span>
              <span>{String((Number(version.data.confidence) * 100).toFixed(0))}%</span>
            </div>
          )}
        </div>

        {/* Expired */}
        {version.expired && (
          <div className="text-xs text-gray-400 mt-1">
            Expired: {new Date(version.expired).toLocaleString()}
          </div>
        )}

        {/* Revert */}
        {!isLatest && onRevert && (
          <button
            onClick={onRevert}
            className="mt-2 text-xs px-3 py-1 border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50"
            data-testid={`revert-btn-${version.version_number}`}
          >
            Revert to v{version.version_number}
          </button>
        )}
      </div>
    </div>
  );
}

export default function EntityHistory({
  classKey,
  onClose,
  onRevert,
}: EntityHistoryProps) {
  const [history, setHistory] = useState<VersionHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reverting, setReverting] = useState<number | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<VersionHistory | Record<string, unknown>[]>(
        `/api/v1/ontology/class/${classKey}/history`,
      );
      if (Array.isArray(res)) {
        const versions: VersionEntry[] = res.map((doc, idx) => ({
          version_number: (doc as Record<string, unknown>).version as number ?? idx + 1,
          data: doc as Record<string, unknown>,
          created: String((doc as Record<string, unknown>).created ?? ""),
          expired: (doc as Record<string, unknown>).expired != null
            ? String((doc as Record<string, unknown>).expired)
            : null,
        }));
        const first = res[0] as Record<string, unknown> | undefined;
        setHistory({
          class_key: classKey,
          uri: String(first?.uri ?? ""),
          label: String(first?.label ?? classKey),
          versions,
        });
      } else {
        setHistory(res as VersionHistory);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load version history",
      );
    } finally {
      setLoading(false);
    }
  }, [classKey]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleRevert = useCallback(
    async (versionNumber: number) => {
      setReverting(versionNumber);
      try {
        await api.post(
          `/api/v1/ontology/class/${classKey}/revert?to_version=${versionNumber}`,
        );
        onRevert?.(classKey, versionNumber);
        await fetchHistory();
      } catch {
        setError("Failed to revert. Please try again.");
      } finally {
        setReverting(null);
      }
    },
    [classKey, onRevert, fetchHistory],
  );

  return (
    <div className="space-y-3" data-testid="entity-history">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">
            Version History
          </h3>
          {history && history.versions && (
            <p className="text-xs text-gray-500 mt-0.5">
              {history.label}{" "}
              <span className="font-mono text-gray-400">
                ({history.versions.length} version
                {history.versions.length !== 1 ? "s" : ""})
              </span>
            </p>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="Close history"
          >
            &times;
          </button>
        )}
      </div>

      {loading && (
        <div className="py-6 text-center text-sm text-gray-400 animate-pulse" data-testid="history-loading">
          Loading version history...
        </div>
      )}

      {error && (
        <div className="py-3 px-3 text-sm text-red-600 bg-red-50 rounded-lg" data-testid="history-error">
          {error}
        </div>
      )}

      {!loading && history && history.versions && (
        <div className="relative ml-1 max-h-[500px] overflow-y-auto">
          {history.versions.map((version, i) => (
            <VersionCard
              key={version.version_number}
              version={version}
              prevVersion={
                i < history.versions.length - 1
                  ? history.versions[i + 1]
                  : undefined
              }
              isLatest={i === 0}
              onRevert={
                reverting === version.version_number
                  ? undefined
                  : () => handleRevert(version.version_number)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
