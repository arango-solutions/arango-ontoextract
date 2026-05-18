"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import { fetchOntologyData } from "@/lib/ontologyDataCache";
import type { OntologyRegistryEntry } from "@/types/curation";
import type { ExtractionRun } from "@/types/pipeline";

/** Per-request ceiling; documents and library use separate AbortControllers so one slow route does not cancel the other. */
const CORE_LOAD_TIMEOUT_MS = 60_000;

function unwrapPaginatedList<T>(res: unknown): T[] {
  if (Array.isArray(res)) return res as T[];
  if (
    res &&
    typeof res === "object" &&
    "data" in res &&
    Array.isArray((res as PaginatedResponse<T>).data)
  ) {
    return (res as PaginatedResponse<T>).data;
  }
  return [];
}

function isAbortError(err: unknown): boolean {
  if (err instanceof Error && err.name === "AbortError") return true;
  return typeof DOMException !== "undefined" && err instanceof DOMException && err.name === "AbortError";
}

interface DocumentEntry {
  _key: string;
  filename: string;
  mime_type?: string;
  chunk_count?: number;
  status?: string;
  upload_date?: string;
}

interface AssetExplorerProps {
  onSelectOntology: (ontologyId: string, displayName?: string) => void;
  onSelectDocument: (docId: string) => void;
  onSelectRun: (runId: string, ontologyId?: string) => void;
  selectedOntologyId: string | null;
  selectedRunId: string | null;
  onContextMenu: (e: React.MouseEvent, type: string, data: unknown) => void;
  /** Increment (e.g. after ontology rename) to refetch documents + library lists. */
  libraryReloadNonce?: number;
  /** The currently selected class key (from graph click or sidebar click). */
  selectedClassKey?: string | null;
  /** Fired when a class row is clicked in the sidebar. */
  onSelectClass?: (classKey: string, ontologyId: string) => void;
  /** The currently selected edge key (from graph click or sidebar click). */
  selectedEdgeKey?: string | null;
  /** Fired when an edge/relation row is clicked in the sidebar. */
  onSelectEdge?: (edgeKey: string, ontologyId: string) => void;
  /** Opens the H.6 standard-ontology catalog browser. Surfaced as a
   *  discoverability hint in the "Ontologies" section empty state and
   *  as a header "+" action so users can find one-click imports without
   *  having to right-click on empty canvas first. */
  onOpenCatalogBrowser?: () => void;
}

type SectionId = "documents" | "ontologies" | "runs";

function HealthBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const color =
    pct >= 80
      ? "bg-green-100 text-green-700"
      : pct >= 50
        ? "bg-amber-100 text-amber-700"
        : "bg-red-100 text-red-700";

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${color}`}>
      {pct}%
    </span>
  );
}

function StatusDot({ status }: { status?: string }) {
  const colors: Record<string, string> = {
    completed: "bg-green-500",
    running: "bg-blue-500 animate-pulse",
    failed: "bg-red-500",
    queued: "bg-gray-400",
    paused: "bg-yellow-500",
    active: "bg-green-500",
    draft: "bg-gray-400",
    processed: "bg-green-500",
    pending: "bg-amber-500",
  };

  return (
    <span
      className={`inline-block h-1.5 w-1.5 rounded-full flex-shrink-0 ${colors[status ?? ""] ?? "bg-gray-300"}`}
      title={status}
    />
  );
}

function formatDuration(ms?: number): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export default function AssetExplorer({
  onSelectOntology,
  onSelectDocument,
  onSelectRun,
  selectedOntologyId,
  selectedRunId,
  onContextMenu,
  libraryReloadNonce = 0,
  selectedClassKey,
  onSelectClass,
  selectedEdgeKey,
  onSelectEdge,
  onOpenCatalogBrowser,
}: AssetExplorerProps) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<SectionId, boolean>>({
    documents: true,
    ontologies: true,
    runs: false,
  });

  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);

  const [ontologies, setOntologies] = useState<OntologyRegistryEntry[]>([]);
  const [ontLoading, setOntLoading] = useState(true);
  const [ontError, setOntError] = useState<string | null>(null);

  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  /** Increment to re-run the core documents + ontology fetch (retry). */
  const [reloadEpoch, setReloadEpoch] = useState(0);

  const searchInputRef = useRef<HTMLInputElement>(null);

  const toggleSection = useCallback((id: SectionId) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const res = await api.get<PaginatedResponse<ExtractionRun> | ExtractionRun[]>(
        "/api/v1/extraction/runs?limit=10",
      );
      const list = Array.isArray(res) ? res : res.data;
      setRuns(list);
    } catch (err) {
      setRunsError(
        err instanceof ApiError ? err.body.message : "Failed to load runs",
      );
    } finally {
      setRunsLoading(false);
    }
  }, []);

  /**
   * Load documents and ontology library independently (separate AbortSignal + timeout each).
   * A slow /ontology/library handler must not abort /documents or vice versa.
   */
  useEffect(() => {
    let cancelled = false;
    const acDoc = new AbortController();
    const acOnt = new AbortController();
    let docTimedOut = false;
    let ontTimedOut = false;

    const timeoutDoc = window.setTimeout(() => {
      docTimedOut = true;
      acDoc.abort();
    }, CORE_LOAD_TIMEOUT_MS);
    const timeoutOnt = window.setTimeout(() => {
      ontTimedOut = true;
      acOnt.abort();
    }, CORE_LOAD_TIMEOUT_MS);

    const timeoutMsg =
      "Request timed out — is the API running and reachable? (ArangoDB or network issues can block the backend.)";

    setDocsLoading(true);
    setOntLoading(true);
    setDocsError(null);
    setOntError(null);

    async function loadDocuments() {
      try {
        const res = await api.get<PaginatedResponse<DocumentEntry> | DocumentEntry[]>(
          "/api/v1/documents",
          { signal: acDoc.signal },
        );
        if (cancelled) return;
        setDocuments(unwrapPaginatedList<DocumentEntry>(res));
      } catch (err) {
        if (cancelled) return;
        if (isAbortError(err)) {
          if (docTimedOut) setDocsError(timeoutMsg);
        } else {
          setDocsError(
            err instanceof ApiError ? err.body.message : "Failed to load documents",
          );
        }
      } finally {
        if (!cancelled) setDocsLoading(false);
      }
    }

    async function loadOntologies() {
      try {
        const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
          "/api/v1/ontology/library",
          { signal: acOnt.signal },
        );
        if (cancelled) return;
        setOntologies(unwrapPaginatedList<OntologyRegistryEntry>(res));
      } catch (err) {
        if (cancelled) return;
        if (isAbortError(err)) {
          if (ontTimedOut) setOntError(timeoutMsg);
        } else {
          setOntError(
            err instanceof ApiError ? err.body.message : "Failed to load ontologies",
          );
        }
      } finally {
        if (!cancelled) setOntLoading(false);
      }
    }

    void Promise.all([loadDocuments(), loadOntologies()]);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutDoc);
      window.clearTimeout(timeoutOnt);
      acDoc.abort();
      acOnt.abort();
    };
  }, [reloadEpoch, libraryReloadNonce]);

  useEffect(() => {
    if (expanded.runs && runs.length === 0 && !runsLoading) {
      fetchRuns();
    }
  }, [expanded.runs, runs.length, runsLoading, fetchRuns]);

  const filteredDocs = search
    ? documents.filter((d) =>
        d.filename.toLowerCase().includes(search.toLowerCase()),
      )
    : documents;

  const ontologyDisplayName = (o: OntologyRegistryEntry) =>
    (o.name?.trim() || o.label?.trim() || o._key).trim();

  const filteredOnt = search
    ? ontologies.filter((o) =>
        ontologyDisplayName(o).toLowerCase().includes(search.toLowerCase()),
      )
    : ontologies;

  const filteredRuns = search
    ? runs.filter((r) =>
        (r.document_name ?? "").toLowerCase().includes(search.toLowerCase()),
      )
    : runs;

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Search */}
      <div className="p-3 border-b border-gray-100">
        <div className="relative">
          <svg
            className="absolute left-2.5 top-2 h-3.5 w-3.5 text-gray-400"
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
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search assets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-md border border-gray-200 bg-gray-50 text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-300 focus:border-blue-300 transition-colors"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1.5 text-gray-400 hover:text-gray-600 text-xs"
              aria-label="Clear search"
            >
              &times;
            </button>
          )}
        </div>
      </div>

      {/* Sections */}
      <div className="flex-1 overflow-y-auto">
        {/* Documents */}
        <Section
          id="documents"
          icon="📄"
          label="Documents"
          count={filteredDocs.length}
          expanded={expanded.documents}
          onToggle={() => toggleSection("documents")}
        >
          {docsLoading && <LoadingRow />}
          {docsError && (
            <ErrorRow
              message={docsError}
              onRetry={() => setReloadEpoch((n) => n + 1)}
            />
          )}
          {!docsLoading && !docsError && filteredDocs.length === 0 && (
            <EmptyRow label="No documents" />
          )}
          {filteredDocs.map((doc) => (
            <DocumentItem
              key={doc._key}
              doc={doc}
              onSelect={() => onSelectDocument(doc._key)}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "document", doc);
              }}
            />
          ))}
        </Section>

        {/* Ontologies */}
        <Section
          id="ontologies"
          icon="🔷"
          label="Ontologies"
          count={filteredOnt.length}
          expanded={expanded.ontologies}
          onToggle={() => toggleSection("ontologies")}
          headerAction={
            onOpenCatalogBrowser
              ? {
                  title: "Browse standard ontology catalog",
                  icon: "📚",
                  onClick: onOpenCatalogBrowser,
                }
              : undefined
          }
        >
          {ontLoading && <LoadingRow />}
          {ontError && (
            <ErrorRow
              message={ontError}
              onRetry={() => setReloadEpoch((n) => n + 1)}
            />
          )}
          {!ontLoading && !ontError && filteredOnt.length === 0 && (
            <div className="px-3 py-3 text-xs text-gray-400 italic flex flex-col gap-1">
              <span>No ontologies.</span>
              {onOpenCatalogBrowser && (
                <button
                  type="button"
                  onClick={onOpenCatalogBrowser}
                  className="text-indigo-600 hover:text-indigo-800 not-italic font-medium text-left"
                >
                  📚 Browse standard catalog…
                </button>
              )}
            </div>
          )}
          {filteredOnt.map((ont) => (
            <OntologyItem
              key={ont._key}
              ont={ont}
              displayName={ontologyDisplayName(ont)}
              isSelected={selectedOntologyId === ont._key}
              onSelect={() => onSelectOntology(ont._key, ontologyDisplayName(ont))}
              onContextMenu={onContextMenu}
              selectedClassKey={selectedOntologyId === ont._key ? selectedClassKey ?? null : null}
              onSelectClass={onSelectClass}
              selectedEdgeKey={selectedOntologyId === ont._key ? selectedEdgeKey ?? null : null}
              onSelectEdge={onSelectEdge}
            />
          ))}
        </Section>

        {/* Pipeline Runs */}
        <Section
          id="runs"
          icon="⚡"
          label="Pipeline Runs"
          count={filteredRuns.length}
          expanded={expanded.runs}
          onToggle={() => toggleSection("runs")}
        >
          {runsLoading && <LoadingRow />}
          {runsError && <ErrorRow message={runsError} onRetry={fetchRuns} />}
          {!runsLoading && !runsError && expanded.runs && filteredRuns.length === 0 && (
            <EmptyRow label="No recent runs" />
          )}
          {filteredRuns.map((run) => (
            <button
              key={run._key}
              onClick={() => onSelectRun(run._key, run.ontology_id)}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "run", run);
              }}
              className={`w-full text-left pl-7 pr-3 py-1.5 text-xs flex items-center gap-2 transition-colors group
                ${selectedRunId === run._key ? "bg-violet-50 text-violet-800" : "hover:bg-gray-50"}
              `}
            >
              <StatusDot status={run.status} />
              <span className={`truncate flex-1 font-medium group-hover:text-gray-900 ${selectedRunId === run._key ? "text-violet-800" : "text-gray-700"}`}>
                {run.document_name}
              </span>
              <span className="text-[10px] text-gray-400 flex-shrink-0">
                {formatDuration(run.duration_ms)}
              </span>
            </button>
          ))}
        </Section>
      </div>
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────── */

function Section({
  id,
  icon,
  label,
  count,
  expanded,
  onToggle,
  children,
  headerAction,
}: {
  id: string;
  icon: string;
  label: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  /** Optional small button rendered after the count in the section header.
   *  Stops click propagation so it never accidentally toggles the section. */
  headerAction?: { title: string; icon: string; onClick: () => void };
}) {
  return (
    <div data-testid={`section-${id}`}>
      <div className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:bg-gray-50 transition-colors">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 flex-1 text-left"
        >
          <span className="text-[10px] text-gray-400 w-3 text-center">
            {expanded ? "▼" : "▶"}
          </span>
          <span>{icon}</span>
          <span>{label}</span>
          <span className="ml-auto text-gray-400 font-normal normal-case">
            {count}
          </span>
        </button>
        {headerAction && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              headerAction.onClick();
            }}
            title={headerAction.title}
            aria-label={headerAction.title}
            className="ml-1 text-gray-400 hover:text-indigo-600 text-sm leading-none px-1 py-0.5 rounded hover:bg-indigo-50"
          >
            {headerAction.icon}
          </button>
        )}
      </div>
      {expanded && <div>{children}</div>}
    </div>
  );
}

function LoadingRow() {
  return (
    <p className="px-3 py-2 text-xs text-gray-400 animate-pulse">Loading...</p>
  );
}

function ErrorRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="px-3 py-2 text-xs text-red-500 flex items-center gap-2">
      <span className="truncate">{message}</span>
      <button
        onClick={onRetry}
        className="text-blue-600 hover:text-blue-800 flex-shrink-0"
      >
        Retry
      </button>
    </div>
  );
}

function EmptyRow({ label }: { label: string }) {
  return (
    <p className="px-3 py-2 text-xs text-gray-400 italic">{label}</p>
  );
}

/* ── Ontology tree ──────────────────────────────────── */

interface OntologyClassEntry {
  _key: string;
  label?: string;
  uri?: string;
  status?: string;
  confidence?: number;
}

interface OntologyEdgeEntry {
  _key: string;
  _from?: string;
  _to?: string;
  label?: string;
  uri?: string;
  edge_type?: string;
  source_label?: string;
  target_label?: string;
}

interface ClassPropertyEntry {
  _key: string;
  label?: string;
  range?: string;
  range_datatype?: string;
  target_class?: { label?: string };
  status?: string;
  confidence?: number;
}

function OntologyItem({
  ont,
  displayName,
  isSelected,
  onSelect,
  onContextMenu,
  selectedClassKey,
  onSelectClass,
  selectedEdgeKey,
  onSelectEdge,
}: {
  ont: OntologyRegistryEntry;
  displayName: string;
  isSelected: boolean;
  onSelect: () => void;
  onContextMenu: (e: React.MouseEvent, type: string, data: unknown) => void;
  selectedClassKey: string | null;
  onSelectClass?: (classKey: string, ontologyId: string) => void;
  selectedEdgeKey: string | null;
  onSelectEdge?: (edgeKey: string, ontologyId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [classesOpen, setClassesOpen] = useState(false);
  const [edgesOpen, setEdgesOpen] = useState(false);

  const [classes, setClasses] = useState<OntologyClassEntry[]>([]);
  const [classesLoading, setClassesLoading] = useState(false);

  const [edges, setEdges] = useState<OntologyEdgeEntry[]>([]);
  const [edgesLoading, setEdgesLoading] = useState(false);

  // Auto-expand the ontology + classes section when a class is selected from the graph
  useEffect(() => {
    if (selectedClassKey) {
      setExpanded(true);
      setClassesOpen(true);
    }
  }, [selectedClassKey]);

  // Auto-expand the ontology + relations section when an edge is selected from the graph
  useEffect(() => {
    if (selectedEdgeKey) {
      setExpanded(true);
      setEdgesOpen(true);
    }
  }, [selectedEdgeKey]);

  useEffect(() => {
    if (!classesOpen || classes.length > 0) return;
    let cancelled = false;
    setClassesLoading(true);
    // ?include=summary -- the AssetExplorer's OntologyClassEntry only
    // reads _key / label / uri / status / confidence, all of which are
    // in the summary projection. Drops the WTW Ontology /classes
    // payload from 909 KB to 360 KB.
    //
    // Also goes through fetchOntologyData so the explorer shares the
    // canvas's cache: once the canvas has loaded WTW classes, expanding
    // the explorer's "classes" tree for the same ontology costs zero
    // extra network round-trips.
    fetchOntologyData(ont._key, "classes", "summary", () =>
      api.get<{ data: OntologyClassEntry[] }>(
        `/api/v1/ontology/${ont._key}/classes?include=summary`,
      ),
    )
      .then((res) => {
        if (!cancelled) {
          const list = Array.isArray(res) ? res : res.data;
          setClasses(Array.isArray(list) ? list : []);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setClassesLoading(false); });
    return () => { cancelled = true; };
  }, [classesOpen, classes.length, ont._key]);

  useEffect(() => {
    if (!edgesOpen || edges.length > 0) return;
    let cancelled = false;
    setEdgesLoading(true);

    // Same ?include=summary rationale as the classes loader above --
    // OntologyEdgeEntry only reads _key / _from / _to / label /
    // edge_type, all in the summary projection. Drops the WTW edges
    // payload from 555 KB to 445 KB.
    //
    // Also routed through fetchOntologyData: in-flight dedup means the
    // canvas's parallel /classes fetch and this explorer's /classes
    // fetch share one network round when they happen at the same time
    // (e.g. user clicks an ontology that auto-expands the relations
    // section).
    const classesPromise = classes.length > 0
      ? Promise.resolve(classes)
      : fetchOntologyData(ont._key, "classes", "summary", () =>
          api.get<{ data: OntologyClassEntry[] }>(
            `/api/v1/ontology/${ont._key}/classes?include=summary`,
          ),
        ).then((res) => {
          const list = Array.isArray(res) ? res : res.data;
          const arr = Array.isArray(list) ? list : [];
          if (!cancelled && classes.length === 0) setClasses(arr);
          return arr;
        });

    Promise.all([
      classesPromise,
      fetchOntologyData(ont._key, "edges", "summary", () =>
        api.get<{ data: OntologyEdgeEntry[] }>(
          `/api/v1/ontology/${ont._key}/edges?include=summary`,
        ),
      ),
    ])
      .then(([clsList, edgeRes]) => {
        if (cancelled) return;
        const rawEdges = Array.isArray(edgeRes) ? edgeRes : edgeRes.data;
        const edgeList = Array.isArray(rawEdges) ? rawEdges : [];

        const classById = new Map<string, string>();
        for (const c of clsList) {
          classById.set(`ontology_classes/${c._key}`, c.label ?? c._key);
          if (c.uri) classById.set(c.uri, c.label ?? c._key);
        }

        const enriched = edgeList.map((e) => ({
          ...e,
          source_label: e.source_label ?? (e._from ? classById.get(e._from) : undefined),
          target_label: e.target_label ?? (e._to ? classById.get(e._to) : undefined),
        }));
        setEdges(enriched);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setEdgesLoading(false); });
    return () => { cancelled = true; };
  }, [edgesOpen, edges.length, ont._key, classes]);

  return (
    <div>
      {/* Ontology row */}
      <button
        onClick={() => {
          setExpanded((v) => !v);
          onSelect();
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          onContextMenu(e, "ontology", ont);
        }}
        className={`w-full text-left pl-5 pr-3 py-1.5 text-xs flex items-center gap-1.5 transition-colors group
          ${isSelected ? "bg-blue-50 text-blue-800" : "hover:bg-gray-50"}
        `}
      >
        <span className="text-[10px] text-gray-400 w-3 text-center flex-shrink-0">
          {expanded ? "▼" : "▶"}
        </span>
        <StatusDot status={ont.status} />
        <span className="truncate flex-1 font-medium group-hover:text-gray-900">
          {displayName}
        </span>
        {ont.current_release_version ? (
          <span className="text-[10px] text-emerald-700 font-medium flex-shrink-0">
            v{ont.current_release_version}
          </span>
        ) : null}
        <span className="text-[10px] text-gray-400 flex-shrink-0">
          {ont.class_count}c
        </span>
        <HealthBadge score={ont.health_score} />
      </button>

      {/* Expanded: Classes + Relations sub-sections */}
      {expanded && (
        <div>
          {/* Classes sub-section */}
          <button
            onClick={() => setClassesOpen((v) => !v)}
            className="w-full text-left pl-10 pr-3 py-1 text-[11px] flex items-center gap-1.5 text-gray-500 hover:bg-gray-50 transition-colors font-medium"
          >
            <span className="text-[9px] text-gray-400 w-3 text-center">
              {classesOpen ? "▼" : "▶"}
            </span>
            <span>Classes</span>
            <span className="text-gray-400 ml-auto">{ont.class_count}</span>
          </button>
          {classesOpen && (
            <div>
              {classesLoading && (
                <p className="pl-16 pr-3 py-1 text-[10px] text-gray-400 animate-pulse">Loading…</p>
              )}
              {!classesLoading && classes.length === 0 && (
                <p className="pl-16 pr-3 py-1 text-[10px] text-gray-400 italic">No classes</p>
              )}
              {classes.map((cls) => (
                <ClassItem
                  key={cls._key}
                  cls={cls}
                  ontologyId={ont._key}
                  onContextMenu={onContextMenu}
                  isSelected={selectedClassKey === cls._key}
                  onSelectClass={onSelectClass}
                />
              ))}
            </div>
          )}

          {/* Relations sub-section */}
          <button
            onClick={() => setEdgesOpen((v) => !v)}
            className="w-full text-left pl-10 pr-3 py-1 text-[11px] flex items-center gap-1.5 text-gray-500 hover:bg-gray-50 transition-colors font-medium"
          >
            <span className="text-[9px] text-gray-400 w-3 text-center">
              {edgesOpen ? "▼" : "▶"}
            </span>
            <span>Relations</span>
            <span className="text-gray-400 ml-auto">{ont.edge_count}</span>
          </button>
          {edgesOpen && (
            <div>
              {edgesLoading && (
                <p className="pl-16 pr-3 py-1 text-[10px] text-gray-400 animate-pulse">Loading…</p>
              )}
              {!edgesLoading && edges.length === 0 && (
                <p className="pl-16 pr-3 py-1 text-[10px] text-gray-400 italic">No relations</p>
              )}
              {edges.map((edge) => {
                const edgeTypeLabels: Record<string, string> = {
                  subclass_of: "subclass of",
                  rdfs_domain: "domain",
                  rdfs_range_class: "range",
                  equivalent_class: "equivalent",
                  has_property: "has property",
                  related_to: "related to",
                };
                const typeLabel = edgeTypeLabels[edge.edge_type ?? ""] ?? edge.edge_type?.replace(/_/g, " ") ?? "";
                const src = edge.source_label ?? edge._from?.split("/").pop()?.replace(/_/g, " ") ?? "";
                const tgt = edge.target_label ?? edge._to?.split("/").pop()?.replace(/_/g, " ") ?? "";
                const displayLabel = edge.label || (src && tgt ? `${src} → ${tgt}` : edge._key);
                const edgeIsSelected = selectedEdgeKey === edge._key;

                return (
                  <EdgeRow
                    key={edge._key}
                    edgeKey={edge._key}
                    displayLabel={displayLabel}
                    typeLabel={typeLabel}
                    title={`${typeLabel}: ${src} → ${tgt}`}
                    isSelected={edgeIsSelected}
                    onClick={() => onSelectEdge?.(edge._key, ont._key)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      onContextMenu(e, "edge", edge);
                    }}
                  />
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ClassItem({
  cls,
  ontologyId,
  onContextMenu,
  isSelected,
  onSelectClass,
}: {
  cls: OntologyClassEntry;
  ontologyId: string;
  onContextMenu: (e: React.MouseEvent, type: string, data: unknown) => void;
  isSelected: boolean;
  onSelectClass?: (classKey: string, ontologyId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [properties, setProperties] = useState<ClassPropertyEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const rowRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!expanded || properties.length > 0) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<Record<string, unknown>>(`/api/v1/ontology/${ontologyId}/classes/${cls._key}`)
      .then((res) => {
        if (cancelled) return;
        const attrs = (res.attributes ?? []) as ClassPropertyEntry[];
        const rels = (res.relationships ?? []) as ClassPropertyEntry[];
        const legacy = (res.legacy_properties ?? []) as ClassPropertyEntry[];
        setProperties([...attrs, ...rels, ...legacy]);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [expanded, properties.length, ontologyId, cls._key]);

  const statusDot: Record<string, string> = {
    approved: "bg-green-500",
    rejected: "bg-red-400",
    pending: "bg-amber-400",
  };

  useEffect(() => {
    if (isSelected && rowRef.current) {
      rowRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isSelected]);

  return (
    <div>
      <button
        ref={rowRef}
        onClick={() => {
          if (onSelectClass) {
            onSelectClass(cls._key, ontologyId);
          }
          setExpanded((v) => !v);
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          onContextMenu(e, "class", { ...cls, ontology_id: ontologyId });
        }}
        className={`w-full text-left pl-14 pr-3 py-1 text-[10px] flex items-center gap-1.5 hover:bg-gray-50 transition-colors group ${
          isSelected ? "bg-indigo-50 ring-1 ring-indigo-300" : ""
        }`}
      >
        <span className="text-[9px] text-gray-400 w-3 text-center flex-shrink-0">
          {expanded ? "▼" : "▶"}
        </span>
        {cls.status && statusDot[cls.status] && (
          <span
            className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${statusDot[cls.status]}`}
            title={cls.status}
          />
        )}
        <span className={`font-medium truncate flex-1 ${isSelected ? "text-indigo-700" : "text-gray-700"} group-hover:text-gray-900`}>
          {cls.label ?? cls._key}
        </span>
        {cls.confidence != null && (
          <span className="text-[9px] text-gray-400 flex-shrink-0">
            {Math.round(cls.confidence * 100)}%
          </span>
        )}
      </button>

      {expanded && (
        <div>
          {loading && (
            <p className="pl-20 pr-3 py-0.5 text-[9px] text-gray-400 animate-pulse">Loading…</p>
          )}
          {!loading && properties.length === 0 && (
            <p className="pl-20 pr-3 py-0.5 text-[9px] text-gray-400 italic">No properties</p>
          )}
          {properties.map((prop, idx) => (
            // ``idx`` is appended to ``_key`` because the backend currently writes
            // duplicate property records (same ``_key``) for the same class — see
            // the demo notes on the duplicate-write dedupe gap. Without the
            // tiebreaker, React warns ``Encountered two children with the same
            // key`` and may drop renders. Once the backend dedupes on write this
            // can revert to ``key={prop._key ?? idx}``.
            <div
              key={`${prop._key ?? "noKey"}-${idx}`}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "property", { ...prop, ontology_id: ontologyId, class_key: cls._key });
              }}
              className="w-full text-left pl-20 pr-3 py-0.5 text-[9px] flex items-center gap-1.5 hover:bg-gray-50 transition-colors cursor-default group"
              title={prop.range_datatype ?? prop.range ?? prop.target_class?.label}
            >
              <span className="text-gray-400 flex-shrink-0">·</span>
              <span className="truncate text-gray-600 group-hover:text-gray-800">
                {prop.label ?? prop._key}
              </span>
              <span className="text-gray-400 truncate ml-auto text-[8px] max-w-[80px]">
                {prop.target_class?.label ?? prop.range_datatype?.replace(/.*#/, "") ?? prop.range?.replace(/.*#/, "") ?? ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EdgeRow({
  edgeKey,
  displayLabel,
  typeLabel,
  title,
  isSelected,
  onClick,
  onContextMenu: onCtx,
}: {
  edgeKey: string;
  displayLabel: string;
  typeLabel: string;
  title: string;
  isSelected: boolean;
  onClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const rowRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isSelected && rowRef.current) {
      rowRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isSelected]);

  return (
    <button
      ref={rowRef}
      key={edgeKey}
      onClick={onClick}
      onContextMenu={onCtx}
      className={`w-full text-left pl-14 pr-3 py-1 text-[10px] flex items-center gap-1.5 hover:bg-gray-50 transition-colors ${
        isSelected ? "bg-indigo-50 ring-1 ring-indigo-300" : ""
      }`}
      title={title}
    >
      <span className="text-purple-400 flex-shrink-0">↔</span>
      <span className={`truncate flex-1 ${isSelected ? "text-indigo-700 font-medium" : "text-gray-700"}`}>
        {displayLabel}
      </span>
      {typeLabel && (
        <span className="text-gray-400 flex-shrink-0 text-[8px]">
          {typeLabel}
        </span>
      )}
    </button>
  );
}

function DocumentItem({
  doc,
  onSelect,
  onContextMenu: onCtx,
}: {
  doc: DocumentEntry;
  onSelect: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [chunks, setChunks] = useState<{ _key: string; text: string; section_heading?: string; chunk_index?: number }[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expanded || chunks.length > 0) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<{ data: { _key: string; text: string; section_heading?: string; chunk_index?: number }[] }>(
        `/api/v1/documents/${doc._key}/chunks`,
      )
      .then((res) => {
        if (!cancelled) {
          const list = Array.isArray(res) ? res : res.data;
          setChunks(Array.isArray(list) ? list : []);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [expanded, chunks.length, doc._key]);

  return (
    <div>
      <button
        onClick={() => {
          setExpanded((v) => !v);
          onSelect();
        }}
        onContextMenu={onCtx}
        className="w-full text-left pl-7 pr-3 py-1.5 text-xs flex items-center gap-2 hover:bg-gray-50 transition-colors group"
      >
        <span className="text-[10px] text-gray-400 w-3 text-center flex-shrink-0">
          {expanded ? "▼" : "▶"}
        </span>
        <StatusDot status={doc.status} />
        <span className="truncate flex-1 text-gray-700 group-hover:text-gray-900">
          {doc.filename}
        </span>
        {doc.chunk_count != null && (
          <span className="text-[10px] text-gray-400 flex-shrink-0">
            {doc.chunk_count}
          </span>
        )}
      </button>
      {expanded && (
        <div>
          {loading && (
            <p className="pl-12 pr-3 py-1 text-[10px] text-gray-400 animate-pulse">Loading chunks…</p>
          )}
          {!loading && chunks.length === 0 && (
            <p className="pl-12 pr-3 py-1 text-[10px] text-gray-400 italic">No chunks</p>
          )}
          {chunks.map((chunk, idx) => (
            <div
              key={chunk._key ?? idx}
              className="pl-12 pr-3 py-1 text-[10px] text-gray-500 truncate hover:bg-gray-50 cursor-default"
              title={chunk.text?.slice(0, 200)}
            >
              <span className="text-gray-400 mr-1">#{chunk.chunk_index ?? idx + 1}</span>
              {chunk.section_heading ? (
                <span className="font-medium text-gray-600">{chunk.section_heading}</span>
              ) : (
                <span className="italic">{chunk.text?.slice(0, 60)}…</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
