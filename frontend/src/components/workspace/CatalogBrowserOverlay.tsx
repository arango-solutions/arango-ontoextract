"use client";

/**
 * Catalog Browser overlay (Stream 1 H.6).
 *
 * Renders the standard ontology catalog (`GET /api/v1/ontology/catalog`)
 * and lets the user one-click-import any entry. Bundled entries import
 * instantly; URL entries can take a few seconds (FOAF, DCMI) to a few
 * minutes (FIBO/Schema.org), so we display a per-row progress indicator
 * and never block other rows while one is in flight.
 *
 * Per `ui-architecture.mdc`:
 *  - This is a workspace overlay, not a new route.
 *  - It is invoked from the canvas right-click menu ("Browse Standard
 *    Catalog…") and from the AssetExplorer "Ontologies" section
 *    empty-state hint. Both routes pass an `onImported` callback the
 *    parent uses to refresh the library and switch to the new ontology.
 *  - The overlay uses `viewportTopRight`-equivalent centred placement
 *    to mirror `ManageImportsOverlay`'s look; an Esc handler + ×
 *    button close it. No destructive native confirmations.
 */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api-client";

interface CatalogSource {
  kind: "bundled" | "url";
  path?: string;
  url?: string;
  format?: string;
  upstream_url?: string;
}

export interface CatalogEntry {
  id: string;
  name: string;
  description?: string;
  uri: string;
  version?: string;
  tier?: string;
  tags?: string[];
  class_count?: number;
  property_count?: number;
  source: CatalogSource;
}

interface CatalogResponse {
  ontologies: CatalogEntry[];
  count: number;
}

interface RegistryEntry {
  _key: string;
}

interface Props {
  /** Set of registry _keys that already exist; their catalog entries
   * are shown as "Imported" with no Import button so the user can't
   * trip into the backend's 409 conflict trap. Optional -- when not
   * passed the overlay fetches the registry itself. */
  existingOntologyIds?: Set<string>;
  onClose: () => void;
  /** Fired once per successful import. Parent should refresh the
   * library and (optionally) select the new ontology. */
  onImported: (newOntologyId: string, catalogId: string) => void;
}

type ImportState =
  | { kind: "idle" }
  | { kind: "running"; catalogId: string }
  | { kind: "success"; catalogId: string; newOntologyId: string }
  | { kind: "error"; catalogId: string; message: string };

export default function CatalogBrowserOverlay({
  existingOntologyIds: existingFromProp,
  onClose,
  onImported,
}: Props) {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [existing, setExisting] = useState<Set<string>>(existingFromProp ?? new Set());
  const [importState, setImportState] = useState<ImportState>({ kind: "idle" });

  // Load the catalog up-front. Cheap (~8KB JSON) so no debounce / pagination.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    api
      .get<CatalogResponse>("/api/v1/ontology/catalog")
      .then((res) => {
        if (cancelled) return;
        setEntries(res.ontologies ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg =
          err instanceof ApiError ? err.body.message : "Failed to load standard ontology catalog";
        setLoadError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // If the parent didn't pre-supply the registry, fetch it so we can
  // disable Import on entries the user already has.
  useEffect(() => {
    if (existingFromProp) return;
    let cancelled = false;
    api
      .get<{ data: RegistryEntry[] }>("/api/v1/ontology/library?limit=200")
      .then((res) => {
        if (cancelled) return;
        setExisting(new Set((res.data ?? []).map((e) => e._key)));
      })
      .catch(() => {
        // Non-critical: worst case the user gets a 409 they can act on.
      });
    return () => {
      cancelled = true;
    };
  }, [existingFromProp]);

  // Esc closes the overlay (UI rule: Esc consistently closes overlays).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleImport = useCallback(
    async (entry: CatalogEntry) => {
      setImportState({ kind: "running", catalogId: entry.id });
      try {
        const res = await api.post<{
          registry_key: string;
          triple_count?: number;
          catalog_id?: string;
        }>(`/api/v1/ontology/catalog/${encodeURIComponent(entry.id)}/import`, {});
        const newId = res.registry_key;
        setImportState({
          kind: "success",
          catalogId: entry.id,
          newOntologyId: newId,
        });
        setExisting((prev) => new Set(prev).add(newId));
        onImported(newId, entry.id);
      } catch (err) {
        const msg = err instanceof ApiError ? err.body.message : String(err);
        setImportState({
          kind: "error",
          catalogId: entry.id,
          message: msg,
        });
      }
    },
    [onImported],
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="catalog-browser-title"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[720px] max-h-[85vh] flex flex-col">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close catalog browser"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 id="catalog-browser-title" className="text-lg font-semibold text-gray-900">
            Standard Ontology Catalog
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            One-click import of well-known ontologies. Bundled entries import instantly; remote
            entries fetch the upstream file on demand and may take a few seconds.
          </p>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1">
          {loading && (
            <div className="flex justify-center py-10">
              <div className="h-8 w-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
            </div>
          )}

          {loadError && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
              {loadError}
            </div>
          )}

          {!loading && !loadError && entries.length === 0 && (
            <p className="text-sm text-gray-400 italic">No catalog entries available.</p>
          )}

          {!loading && !loadError && entries.length > 0 && (
            <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
              {entries.map((entry) => {
                const isImported = existing.has(entry.id);
                const isRunning =
                  importState.kind === "running" && importState.catalogId === entry.id;
                const justSucceeded =
                  importState.kind === "success" && importState.catalogId === entry.id;
                const justFailed =
                  importState.kind === "error" && importState.catalogId === entry.id;

                return (
                  <li
                    key={entry.id}
                    data-testid={`catalog-entry-${entry.id}`}
                    className="px-4 py-3.5"
                  >
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-sm font-semibold text-gray-900 truncate">
                            {entry.name}
                          </p>
                          <SourceBadge kind={entry.source.kind} />
                          {entry.tier && <TierBadge tier={entry.tier} />}
                        </div>
                        {entry.description && (
                          <p className="text-xs text-gray-600 mt-1 line-clamp-2">
                            {entry.description}
                          </p>
                        )}
                        <div className="mt-1.5 flex items-center gap-3 text-[11px] text-gray-500">
                          {entry.class_count != null && (
                            <span>
                              <span className="font-mono">{entry.class_count}</span> classes
                            </span>
                          )}
                          {entry.property_count != null && (
                            <span>
                              <span className="font-mono">{entry.property_count}</span> properties
                            </span>
                          )}
                          <span className="font-mono text-gray-400 truncate">{entry.uri}</span>
                        </div>
                        {entry.tags && entry.tags.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {entry.tags.map((tag) => (
                              <span
                                key={tag}
                                className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                        {justFailed && (
                          <p className="mt-2 text-xs text-red-600">
                            Import failed: {importState.message}
                          </p>
                        )}
                        {justSucceeded && (
                          <p className="mt-2 text-xs text-green-600">
                            Imported as <span className="font-mono">{importState.newOntologyId}</span>.
                          </p>
                        )}
                      </div>
                      <div className="flex-shrink-0">
                        <ImportButton
                          isImported={isImported}
                          isRunning={isRunning}
                          isDisabled={importState.kind === "running"}
                          onClick={() => handleImport(entry)}
                        />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function ImportButton({
  isImported,
  isRunning,
  isDisabled,
  onClick,
}: {
  isImported: boolean;
  isRunning: boolean;
  isDisabled: boolean;
  onClick: () => void;
}) {
  if (isImported) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 bg-green-50 text-green-700 rounded-md font-medium">
        ✓ Imported
      </span>
    );
  }
  if (isRunning) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-md font-medium">
        <span className="h-3 w-3 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        Importing…
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      className="text-xs font-medium px-3 py-1.5 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
    >
      Import
    </button>
  );
}

function SourceBadge({ kind }: { kind: "bundled" | "url" }) {
  if (kind === "bundled") {
    return (
      <span
        className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700"
        title="Imports from the file shipped with this AOE installation -- works offline."
      >
        bundled
      </span>
    );
  }
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700"
      title="Fetches the upstream file at import time -- requires network access."
    >
      remote
    </span>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const color =
    tier === "core"
      ? "bg-amber-50 text-amber-700"
      : tier === "domain"
        ? "bg-blue-50 text-blue-700"
        : "bg-gray-100 text-gray-600";
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${color}`}>{tier}</span>;
}
