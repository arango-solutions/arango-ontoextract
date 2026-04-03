"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type { OntologyRegistryEntry } from "@/types/curation";
import type { ExtractionRun } from "@/types/pipeline";

interface DocumentEntry {
  _key: string;
  filename: string;
  mime_type?: string;
  chunk_count?: number;
  status?: string;
  upload_date?: string;
}

interface AssetExplorerProps {
  onSelectOntology: (ontologyId: string) => void;
  onSelectDocument: (docId: string) => void;
  onSelectRun: (runId: string) => void;
  selectedOntologyId: string | null;
  onContextMenu: (e: React.MouseEvent, type: string, data: unknown) => void;
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
  onContextMenu,
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

  const searchInputRef = useRef<HTMLInputElement>(null);

  const toggleSection = useCallback((id: SectionId) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const fetchDocuments = useCallback(async () => {
    setDocsLoading(true);
    setDocsError(null);
    try {
      const res = await api.get<PaginatedResponse<DocumentEntry> | DocumentEntry[]>(
        "/api/v1/documents",
      );
      const list = Array.isArray(res) ? res : res.data;
      setDocuments(list);
    } catch (err) {
      setDocsError(
        err instanceof ApiError ? err.body.message : "Failed to load documents",
      );
    } finally {
      setDocsLoading(false);
    }
  }, []);

  const fetchOntologies = useCallback(async () => {
    setOntLoading(true);
    setOntError(null);
    try {
      const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
        "/api/v1/ontology/library",
      );
      setOntologies(res.data);
    } catch (err) {
      setOntError(
        err instanceof ApiError ? err.body.message : "Failed to load ontologies",
      );
    } finally {
      setOntLoading(false);
    }
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

  useEffect(() => {
    fetchDocuments();
    fetchOntologies();
  }, [fetchDocuments, fetchOntologies]);

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

  const filteredOnt = search
    ? ontologies.filter((o) =>
        o.name.toLowerCase().includes(search.toLowerCase()),
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
          {docsError && <ErrorRow message={docsError} onRetry={fetchDocuments} />}
          {!docsLoading && !docsError && filteredDocs.length === 0 && (
            <EmptyRow label="No documents" />
          )}
          {filteredDocs.map((doc) => (
            <button
              key={doc._key}
              onClick={() => onSelectDocument(doc._key)}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "document", doc);
              }}
              className="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-gray-50 transition-colors group"
            >
              <StatusDot status={doc.status} />
              <span className="truncate flex-1 text-gray-700 group-hover:text-gray-900">
                {doc.filename}
              </span>
              {doc.chunk_count != null && (
                <span className="text-[10px] text-gray-400 flex-shrink-0">
                  {doc.chunk_count} chunks
                </span>
              )}
            </button>
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
        >
          {ontLoading && <LoadingRow />}
          {ontError && <ErrorRow message={ontError} onRetry={fetchOntologies} />}
          {!ontLoading && !ontError && filteredOnt.length === 0 && (
            <EmptyRow label="No ontologies" />
          )}
          {filteredOnt.map((ont) => (
            <button
              key={ont._key}
              onClick={() => onSelectOntology(ont._key)}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "ontology", ont);
              }}
              className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors group
                ${selectedOntologyId === ont._key ? "bg-blue-50 text-blue-800" : "hover:bg-gray-50"}
              `}
            >
              <StatusDot status={ont.status} />
              <span className="truncate flex-1 font-medium group-hover:text-gray-900">
                {ont.name}
              </span>
              <span className="text-[10px] text-gray-400 flex-shrink-0">
                {ont.class_count}c
              </span>
              <HealthBadge score={ont.health_score} />
            </button>
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
              onClick={() => onSelectRun(run._key)}
              onContextMenu={(e) => {
                e.preventDefault();
                onContextMenu(e, "run", run);
              }}
              className="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-gray-50 transition-colors group"
            >
              <StatusDot status={run.status} />
              <span className="truncate flex-1 text-gray-700 group-hover:text-gray-900">
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
}: {
  id: string;
  icon: string;
  label: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div data-testid={`section-${id}`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:bg-gray-50 transition-colors"
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
