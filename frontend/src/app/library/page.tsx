"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type {
  OntologyRegistryEntry,
  OntologyClass,
  SearchResponse,
  SearchResult,
} from "@/types/curation";
import OntologyCard from "@/components/library/OntologyCard";
import ClassHierarchy from "@/components/library/ClassHierarchy";
import QualityPanel from "@/components/library/QualityPanel";

interface ClassDetail extends OntologyClass {
  properties?: {
    _key: string;
    label: string;
    description?: string;
    range?: string;
    rdf_type?: string;
    confidence?: number;
  }[];
}

interface SourceDocument {
  _key: string;
  filename: string;
  mime_type?: string;
  upload_date?: string;
  chunk_count?: number;
}

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  registry: { label: "Ontology", color: "bg-blue-100 text-blue-700" },
  class: { label: "Class", color: "bg-purple-100 text-purple-700" },
  property: { label: "Property", color: "bg-amber-100 text-amber-700" },
};

function SearchResultsPanel({
  results,
  onOntologyClick,
}: {
  results: SearchResponse;
  onOntologyClick: (key: string) => void;
}) {
  const totalCount =
    results.counts.registry +
    results.counts.classes +
    results.counts.properties;

  if (totalCount === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        <p className="text-sm">
          No results found for &ldquo;{results.query}&rdquo;
        </p>
      </div>
    );
  }

  const allResults: SearchResult[] = [
    ...results.results.registry,
    ...results.results.classes,
    ...results.results.properties,
  ].sort((a, b) => b.score - a.score);

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <p className="text-sm text-gray-600">
          <span className="font-semibold text-gray-800">{totalCount}</span>{" "}
          result{totalCount !== 1 ? "s" : ""} for &ldquo;{results.query}&rdquo;
        </p>
      </div>
      <div className="divide-y divide-gray-50">
        {allResults.map((item) => {
          const src = SOURCE_LABELS[item.source] ?? SOURCE_LABELS.class;
          const title = item.name ?? item.label ?? item._key;
          return (
            <button
              key={`${item.source}-${item._key}`}
              onClick={() => {
                const targetKey =
                  item.source === "registry"
                    ? item._key
                    : item.ontology_id ?? item._key;
                onOntologyClick(targetKey);
              }}
              className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${src.color}`}
                >
                  {src.label}
                </span>
                <span className="text-sm font-medium text-gray-900">
                  {title}
                </span>
                {item.ontology_name && item.source !== "registry" && (
                  <span className="text-xs text-gray-400 ml-auto">
                    in {item.ontology_name}
                  </span>
                )}
              </div>
              {item.description && (
                <p className="text-xs text-gray-500 line-clamp-1">
                  {item.description}
                </p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function LibraryPage() {
  const [ontologies, setOntologies] = useState<OntologyRegistryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedOntologyId, setSelectedOntologyId] = useState<string | null>(
    null,
  );
  const [selectedClass, setSelectedClass] = useState<ClassDetail | null>(null);
  const [classLoading, setClassLoading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [tierFilter, setTierFilter] = useState<"all" | "domain" | "local">(
    "all",
  );
  const [sourceDocuments, setSourceDocuments] = useState<SourceDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [addingDoc, setAddingDoc] = useState(false);
  const addDocRef = useRef<HTMLInputElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(
    null,
  );
  const [searchLoading, setSearchLoading] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const allTags = Array.from(
    new Set(ontologies.flatMap((o) => o.tags ?? [])),
  ).sort();

  const fetchOntologies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
        "/api/v1/ontology/library",
      );
      setOntologies(res.data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load ontology library",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const performSearch = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults(null);
      return;
    }
    setSearchLoading(true);
    try {
      const res = await api.get<SearchResponse>(
        `/api/v1/ontology/search?q=${encodeURIComponent(query.trim())}`,
      );
      setSearchResults(res);
    } catch {
      setSearchResults(null);
    } finally {
      setSearchLoading(false);
    }
  }, []);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchQuery(value);
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
      searchTimerRef.current = setTimeout(() => performSearch(value), 300);
    },
    [performSearch],
  );

  const clearSearch = useCallback(() => {
    setSearchQuery("");
    setSearchResults(null);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
  }, []);

  useEffect(() => {
    fetchOntologies();
  }, [fetchOntologies]);

  const loadSourceDocuments = useCallback(async (ontologyId: string) => {
    setDocsLoading(true);
    try {
      const res = await api.get<{ documents: SourceDocument[] }>(
        `/api/v1/ontology/library/${ontologyId}/documents`,
      );
      setSourceDocuments(res.documents ?? []);
    } catch {
      setSourceDocuments([]);
    } finally {
      setDocsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedOntologyId) {
      loadSourceDocuments(selectedOntologyId);
    } else {
      setSourceDocuments([]);
    }
  }, [selectedOntologyId, loadSourceDocuments]);

  const handleAddDocument = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !selectedOntologyId) return;
      setAddingDoc(true);
      try {
        const baseUrl =
          process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(
          `${baseUrl}/api/v1/ontology/library/${selectedOntologyId}/add-document`,
          { method: "POST", body: formData },
        );
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(
            err.detail ?? err.error?.message ?? `Upload failed (${res.status})`,
          );
        }
        window.location.href = "/pipeline";
      } catch (err) {
        alert(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setAddingDoc(false);
        if (addDocRef.current) addDocRef.current.value = "";
      }
    },
    [selectedOntologyId],
  );

  const handleClassSelect = useCallback(
    async (classKey: string) => {
      if (!selectedOntologyId) return;
      setClassLoading(true);
      try {
        const [classRes, edgeRes] = await Promise.all([
          api.get<{ data: ClassDetail[] }>(
            `/api/v1/ontology/${selectedOntologyId}/classes`,
          ),
          api.get<{
            data: { _from: string; _to: string; edge_type?: string }[];
          }>(`/api/v1/ontology/${selectedOntologyId}/edges`),
        ]);

        const cls = classRes.data.find((c) => c._key === classKey);
        if (!cls) {
          setSelectedClass(null);
          return;
        }

        const propEdges = edgeRes.data.filter((e) => {
          const et = e.edge_type ?? (e as Record<string, unknown>).type;
          return (
            et === "has_property" &&
            e._from === `ontology_classes/${classKey}`
          );
        });

        let properties: ClassDetail["properties"] = [];
        if (propEdges.length > 0) {
          const propKeys = propEdges
            .map((e) => e._to.split("/").pop() ?? e._to)
            .join(",");
          try {
            const propsRes = await api.get<{
              data: NonNullable<ClassDetail["properties"]>;
            }>(
              `/api/v1/ontology/${selectedOntologyId}/properties?keys=${propKeys}`,
            );
            properties = propsRes.data;
          } catch {
            // property fetch failed, show class without properties
          }
        }

        setSelectedClass({ ...cls, properties });
      } catch {
        setSelectedClass(null);
      } finally {
        setClassLoading(false);
      }
    },
    [selectedOntologyId],
  );

  const filtered = ontologies.filter((o) => {
    if (tierFilter !== "all" && o.tier !== tierFilter) return false;
    if (tagFilter && !(o.tags ?? []).includes(tagFilter)) return false;
    return true;
  });

  const selectedOntology = ontologies.find(
    (o) => o._key === selectedOntologyId,
  );

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Ontology Library
            </h1>
            <p className="text-sm text-gray-500">
              Browse registered ontologies and explore class hierarchies.
            </p>
          </div>
          <a
            href="/"
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Home
          </a>
        </div>
      </header>

      <div className="max-w-[1600px] mx-auto px-6 py-6">
        {/* Search bar (J.7) */}
        <div className="mb-4 relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search ontologies, classes, and properties..."
            className="w-full px-4 py-2.5 pl-10 rounded-lg border border-gray-200 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-300 transition-colors"
            data-testid="library-search"
          />
          <svg
            className="absolute left-3 top-3 h-4 w-4 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          {searchQuery && (
            <button
              onClick={clearSearch}
              className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600 text-sm"
              aria-label="Clear search"
            >
              &times;
            </button>
          )}
        </div>

        {/* Tier + Tag filters */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <span className="text-sm text-gray-500">Filter:</span>
          {(["all", "domain", "local"] as const).map((tier) => (
            <button
              key={tier}
              onClick={() => setTierFilter(tier)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                tierFilter === tier
                  ? "bg-blue-50 text-blue-700 border-blue-200 font-medium"
                  : "text-gray-500 border-gray-200 hover:bg-gray-50"
              }`}
              data-testid={`filter-${tier}`}
            >
              {tier === "all"
                ? `All (${ontologies.length})`
                : tier === "domain"
                  ? `Domain (${ontologies.filter((o) => o.tier === "domain").length})`
                  : `Local (${ontologies.filter((o) => o.tier === "local").length})`}
            </button>
          ))}

          {allTags.length > 0 && (
            <>
              <span className="text-gray-300">|</span>
              <span className="text-sm text-gray-500">Tags:</span>
              {allTags.map((tag) => (
                <button
                  key={tag}
                  onClick={() =>
                    setTagFilter((prev) => (prev === tag ? null : tag))
                  }
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    tagFilter === tag
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200 font-medium"
                      : "text-gray-500 border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  {tag}
                </button>
              ))}
            </>
          )}
        </div>

        {loading && (
          <div className="text-center py-12">
            <p className="text-gray-400 animate-pulse">
              Loading ontology library...
            </p>
          </div>
        )}

        {error && (
          <div className="text-center py-12">
            <p className="text-red-500 mb-3">{error}</p>
            <button
              onClick={fetchOntologies}
              className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Retry
            </button>
          </div>
        )}

        {/* Search results (J.7) */}
        {searchQuery && (searchLoading || searchResults) && (
          <div className="mb-6">
            {searchLoading && (
              <p className="text-sm text-gray-400 animate-pulse py-4">
                Searching...
              </p>
            )}
            {!searchLoading && searchResults && (
              <SearchResultsPanel
                results={searchResults}
                onOntologyClick={(key) => {
                  setSelectedOntologyId(key);
                  setSelectedClass(null);
                  clearSearch();
                }}
              />
            )}
          </div>
        )}

        {!loading && !error && !searchResults && (
          <div className="flex gap-6">
            <div className="flex-[7]">
              {filtered.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p className="text-lg">No ontologies found.</p>
                  <p className="text-sm mt-1">
                    Upload a document and run extraction to create one.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filtered.map((ontology) => (
                    <OntologyCard
                      key={ontology._key}
                      ontology={ontology}
                      onClick={(key) => {
                        setSelectedOntologyId(key);
                        setSelectedClass(null);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>

            {selectedOntology && (
              <aside className="flex-[3] space-y-4 self-start sticky top-6">
                {/* Class Hierarchy */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h2 className="text-sm font-semibold text-gray-800">
                        {selectedOntology.name}
                      </h2>
                      <p className="text-xs text-gray-500">Class Hierarchy</p>
                    </div>
                    <button
                      onClick={() => {
                        setSelectedOntologyId(null);
                        setSelectedClass(null);
                      }}
                      className="text-gray-400 hover:text-gray-600 text-lg leading-none"
                      aria-label="Close hierarchy"
                    >
                      &times;
                    </button>
                  </div>

                  {/* Action buttons */}
                  <div className="flex gap-2 mb-3">
                    <a
                      href={`/ontology/${selectedOntology._key}/edit`}
                      className="flex-1 text-center text-xs px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
                    >
                      Edit Graph
                    </a>
                    <a
                      href={`/curation/${selectedOntology.extraction_run_id ?? selectedOntology._key}`}
                      className="flex-1 text-center text-xs px-3 py-2 border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-lg transition-colors font-medium"
                    >
                      Curate
                    </a>
                    <div className="relative">
                      <button
                        onClick={() => setExportOpen((v) => !v)}
                        onBlur={() => setTimeout(() => setExportOpen(false), 150)}
                        className="text-xs px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors font-medium"
                      >
                        Export ▾
                      </button>
                      {exportOpen && (
                        <div className="absolute right-0 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
                          {(["turtle", "jsonld", "csv"] as const).map((fmt) => {
                            const baseUrl =
                              process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
                            const label = fmt === "turtle" ? "OWL / Turtle" : fmt === "jsonld" ? "JSON-LD" : "CSV";
                            return (
                              <a
                                key={fmt}
                                href={`${baseUrl}/api/v1/ontology/${selectedOntology._key}/export?format=${fmt}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => setExportOpen(false)}
                                className="block px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                              >
                                {label}
                              </a>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>

                  <QualityPanel ontologyId={selectedOntology._key} />

                  {/* Add Document */}
                  <div className="mb-3">
                    <input
                      ref={addDocRef}
                      type="file"
                      accept=".pdf,.docx,.md"
                      onChange={handleAddDocument}
                      className="hidden"
                    />
                    <button
                      onClick={() => addDocRef.current?.click()}
                      disabled={addingDoc}
                      className="w-full text-xs px-3 py-2 bg-green-600 hover:bg-green-700 disabled:bg-green-400 text-white rounded-lg transition-colors font-medium flex items-center justify-center gap-1.5"
                    >
                      {addingDoc ? (
                        <>
                          <span className="h-3 w-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          Adding…
                        </>
                      ) : (
                        "+ Add Document"
                      )}
                    </button>
                  </div>

                  <ClassHierarchy
                    ontologyId={selectedOntology._key}
                    onClassSelect={handleClassSelect}
                  />

                  {/* Source documents (G.7) */}
                  {docsLoading ? (
                    <p className="text-xs text-gray-400 animate-pulse mt-3">
                      Loading documents…
                    </p>
                  ) : sourceDocuments.length > 0 ? (
                    <div className="mt-4 border-t border-gray-100 pt-3">
                      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                        Source Documents ({sourceDocuments.length})
                      </h4>
                      <ul className="space-y-1.5">
                        {sourceDocuments.map((doc) => (
                          <li
                            key={doc._key}
                            className="text-xs px-2 py-1.5 rounded bg-gray-50 flex items-center justify-between"
                          >
                            <span className="text-gray-700 truncate font-medium">
                              {doc.filename}
                            </span>
                            {doc.chunk_count != null && (
                              <span className="text-gray-400 ml-2 flex-shrink-0">
                                {doc.chunk_count} chunks
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>

                {/* Class Detail Panel */}
                {classLoading && (
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                    <p className="text-sm text-gray-400 animate-pulse text-center py-4">
                      Loading class details...
                    </p>
                  </div>
                )}

                {!classLoading && selectedClass && (
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-4">
                    <div>
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-gray-800">
                          {selectedClass.label}
                        </h3>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
                          {selectedClass.rdf_type ?? "owl:Class"}
                        </span>
                      </div>
                      {selectedClass.uri && (
                        <p className="text-xs text-gray-400 mt-0.5 font-mono truncate">
                          {selectedClass.uri}
                        </p>
                      )}
                    </div>

                    {selectedClass.description && (
                      <p className="text-sm text-gray-600 leading-relaxed">
                        {selectedClass.description}
                      </p>
                    )}

                    <div className="flex items-center gap-4 text-xs text-gray-500">
                      <span>
                        Confidence:{" "}
                        <strong className="text-gray-700">
                          {((selectedClass.confidence ?? 0) * 100).toFixed(0)}%
                        </strong>
                      </span>
                      {selectedClass.ontology_id && (
                        <span className="truncate">
                          Ontology: {selectedClass.ontology_id}
                        </span>
                      )}
                    </div>

                    {/* Properties */}
                    {selectedClass.properties &&
                      selectedClass.properties.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                            Properties ({selectedClass.properties.length})
                          </h4>
                          <div className="space-y-1.5">
                            {selectedClass.properties.map((prop) => (
                              <div
                                key={prop._key}
                                className="flex items-start gap-2 text-sm px-2 py-1.5 rounded bg-gray-50"
                              >
                                <span className="text-purple-600 font-medium flex-shrink-0">
                                  {prop.label}
                                </span>
                                {prop.range && (
                                  <span className="text-xs text-gray-400 ml-auto flex-shrink-0 font-mono">
                                    {prop.range}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Class-level actions */}
                    <a
                      href={`/curation/${selectedOntology.extraction_run_id ?? selectedOntology._key}?focus=${selectedClass._key}`}
                      className="block w-full text-center text-xs px-3 py-2 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-lg transition-colors font-medium"
                    >
                      View in Curation Dashboard
                    </a>
                  </div>
                )}
              </aside>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
