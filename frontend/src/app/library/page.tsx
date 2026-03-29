"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type { OntologyRegistryEntry, OntologyClass } from "@/types/curation";
import OntologyCard from "@/components/library/OntologyCard";
import ClassHierarchy from "@/components/library/ClassHierarchy";

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

export default function LibraryPage() {
  const [ontologies, setOntologies] = useState<OntologyRegistryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedOntologyId, setSelectedOntologyId] = useState<string | null>(
    null,
  );
  const [selectedClass, setSelectedClass] = useState<ClassDetail | null>(null);
  const [classLoading, setClassLoading] = useState(false);
  const [tierFilter, setTierFilter] = useState<"all" | "domain" | "local">(
    "all",
  );

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

  useEffect(() => {
    fetchOntologies();
  }, [fetchOntologies]);

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

  const filtered =
    tierFilter === "all"
      ? ontologies
      : ontologies.filter((o) => o.tier === tierFilter);

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
        <div className="flex items-center gap-3 mb-6">
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

        {!loading && !error && (
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
                      href={`/curation/${selectedOntology.extraction_run_id ?? selectedOntology._key}`}
                      className="flex-1 text-center text-xs px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
                    >
                      Curate Ontology
                    </a>
                    <div className="relative group/export">
                      <button className="text-xs px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors font-medium">
                        Export ▾
                      </button>
                      <div className="hidden group-hover/export:block absolute right-0 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
                        {(["turtle", "jsonld", "csv"] as const).map((fmt) => {
                          const baseUrl =
                            process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
                          const label = fmt === "turtle" ? "OWL / Turtle" : fmt === "jsonld" ? "JSON-LD" : "CSV";
                          return (
                            <a
                              key={fmt}
                              href={`${baseUrl}/api/v1/ontology/${selectedOntology._key}/export?format=${fmt}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                            >
                              {label}
                            </a>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  <ClassHierarchy
                    ontologyId={selectedOntology._key}
                    onClassSelect={handleClassSelect}
                  />
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
