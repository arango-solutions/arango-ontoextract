"use client";

/**
 * Relational Schema Extraction overlay.
 *
 * The relational (SQL) analogue of ``SchemaExtractionOverlay`` (which targets
 * ArangoDB). Lets a curator point AOE at a relational database — PostgreSQL,
 * MySQL, SQL Server, Snowflake, DuckDB, Databricks, or a CSV directory —
 * preview its tables / columns / foreign keys, optionally layer existing AOE
 * ontologies on top via ``owl:imports``, and commit the reverse-engineered
 * ontology to the AOE registry.
 *
 * Per ``ui-architecture.mdc``:
 *  - Overlay over the workspace canvas, never a new route (rule 9).
 *  - Opened from the canvas right-click menu ("Extract from Relational DB…",
 *    next to "Extract from ArangoDB…" — both are add-an-ontology actions).
 *    Esc + × close.
 *  - The connection string lives in form state only, never persisted; the
 *    backend matches this by accepting POST (not GET) for both
 *    ``/schema/relational/tables`` and ``/schema/relational/extract`` so DSNs
 *    (which can embed credentials) never leak via URLs / referrer headers.
 *
 * Three-step state machine, all in one component (state, not routes):
 *
 *   ┌──────────┐   preview    ┌──────────┐   extract   ┌────────┐
 *   │ connect  │ ───────────► │ preview  │ ──────────► │ result │
 *   │ (form)   │              │ (tables) │             │        │
 *   └──────────┘ ◄──────────  └──────────┘             └────────┘
 *                  "Back"
 *
 * Backend endpoints:
 *
 *   POST /api/v1/ontology/schema/relational/tables    -> topology preview
 *   POST /api/v1/ontology/schema/relational/extract   -> commit (TTL gen + import)
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Wire types -- mirror app/services/relational_schema_extraction.py and the
// ``/schema/relational/tables`` + ``/schema/relational/extract`` responses.
// ---------------------------------------------------------------------------

/** Supported relational sources — mirrors ``SUPPORTED_SOURCE_TYPES`` in the
 *  relational-schema-analyzer library. */
export const SOURCE_TYPES: { id: string; label: string; urlHint: string }[] = [
  { id: "postgresql", label: "PostgreSQL", urlHint: "postgresql://user:pass@host:5432/dbname" },
  { id: "mysql", label: "MySQL", urlHint: "mysql://user:pass@host:3306/dbname" },
  { id: "sqlserver", label: "SQL Server", urlHint: "mssql://user:pass@host:1433/dbname" },
  { id: "snowflake", label: "Snowflake", urlHint: "snowflake://user:pass@account/dbname" },
  { id: "duckdb", label: "DuckDB", urlHint: "/path/to/database.duckdb" },
  { id: "databricks", label: "Databricks", urlHint: "databricks://token@host/http_path" },
  { id: "csv", label: "CSV directory", urlHint: "/path/to/csv/directory" },
];

interface RelationalColumn {
  name: string;
  data_type: string;
  type_category: string | null;
  nullable: boolean;
  primary_key: boolean;
  unique: boolean;
}

interface RelationalForeignKey {
  columns: string[];
  foreign_table: string;
  foreign_columns: string[];
}

interface RelationalTable {
  name: string;
  is_view: boolean;
  comment: string | null;
  column_count: number;
  primary_key: string[];
  columns: RelationalColumn[];
  foreign_keys: RelationalForeignKey[];
}

interface PreviewResponse {
  source_type: string;
  schema_name: string;
  db_label: string;
  server_version: string | null;
  dialect: string | null;
  tables: RelationalTable[];
  table_count: number;
  view_count: number;
  foreign_key_count: number;
}

interface ExtractResponse {
  run_id: string;
  status: string;
  ontology_id: string;
  import_stats: Record<string, unknown>;
  provenance: Record<string, unknown>;
  provenance_stamped: number;
}

interface RegistryEntry {
  _key: string;
  name?: string;
}

// ---------------------------------------------------------------------------
// Connection form state.
// ---------------------------------------------------------------------------

interface ConnectionConfig {
  source_type: string;
  url: string;
  schema_name: string;
  db_label: string;
  ontology_label: string;
}

const EMPTY_CONNECTION: ConnectionConfig = {
  source_type: "postgresql",
  url: "",
  schema_name: "public",
  db_label: "",
  ontology_label: "",
};

type StepState =
  | { step: "connect"; submitting: boolean; error: string | null }
  | {
      step: "preview";
      preview: PreviewResponse;
      extractConstraints: boolean;
      imports: Set<string>;
      submitting: boolean;
      error: string | null;
    }
  | { step: "result"; result: ExtractResponse };

interface Props {
  onClose: () => void;
  /** Fired once on a successful extract so the parent can refresh the library
   *  and switch to the newly created ontology. Receives the AOE registry key. */
  onImported: (newOntologyId: string) => void;
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests).
// ---------------------------------------------------------------------------

/** Count classes / datatype properties / object properties the extract *will*
 *  create from a preview. Pure — exported so tests can pin the count math
 *  without rendering. Tables (incl. views) become classes; columns become
 *  datatype properties; foreign keys become object properties. */
export function summarizeRelationalExtraction(preview: PreviewResponse): {
  classes: number;
  datatypeProperties: number;
  objectProperties: number;
} {
  return {
    classes: preview.table_count,
    datatypeProperties: preview.tables.reduce((sum, t) => sum + t.column_count, 0),
    objectProperties: preview.foreign_key_count,
  };
}

/** Trim + validate the connection form before hitting the network. Returns
 *  ``null`` when valid, otherwise the first user-visible error. Pure —
 *  exported for tests. */
export function validateRelationalConnection(c: ConnectionConfig): string | null {
  if (!c.source_type.trim()) return "Source type is required.";
  if (!SOURCE_TYPES.some((s) => s.id === c.source_type)) {
    return `Unsupported source type: ${c.source_type}.`;
  }
  if (!c.url.trim()) return "Connection string / path is required.";
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RelationalExtractionOverlay({ onClose, onImported }: Props) {
  const [connection, setConnection] = useState<ConnectionConfig>(EMPTY_CONNECTION);
  const [state, setState] = useState<StepState>({
    step: "connect",
    submitting: false,
    error: null,
  });
  const [registry, setRegistry] = useState<RegistryEntry[]>([]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Step 1 → 2: preview
  const handlePreview = useCallback(async () => {
    const validationError = validateRelationalConnection(connection);
    if (validationError) {
      setState({ step: "connect", submitting: false, error: validationError });
      return;
    }
    setState({ step: "connect", submitting: true, error: null });
    try {
      const preview = await api.post<PreviewResponse>(
        "/api/v1/ontology/schema/relational/tables",
        {
          source_type: connection.source_type,
          url: connection.url.trim(),
          schema_name: connection.schema_name.trim() || "public",
          db_label: connection.db_label.trim() || undefined,
        },
      );
      setState({
        step: "preview",
        preview,
        extractConstraints: true,
        imports: new Set(),
        submitting: false,
        error: null,
      });
      api
        .get<{ data: RegistryEntry[] }>("/api/v1/ontology/library?limit=100")
        .then((res) => setRegistry(res.data ?? []))
        .catch(() => {
          /* picker stays empty */
        });
    } catch (err) {
      const msg = err instanceof ApiError ? err.body.message : String(err);
      setState({ step: "connect", submitting: false, error: msg });
    }
  }, [connection]);

  // Step 2 → 3: extract
  const handleExtract = useCallback(async () => {
    if (state.step !== "preview") return;
    setState({ ...state, submitting: true, error: null });
    try {
      const result = await api.post<ExtractResponse>(
        "/api/v1/ontology/schema/relational/extract",
        {
          source_type: connection.source_type,
          url: connection.url.trim(),
          schema_name: connection.schema_name.trim() || "public",
          db_label: connection.db_label.trim() || undefined,
          extract_constraints: state.extractConstraints,
          imports: Array.from(state.imports),
          ontology_label: connection.ontology_label.trim() || undefined,
        },
      );
      setState({ step: "result", result });
      onImported(result.ontology_id);
    } catch (err) {
      const msg = err instanceof ApiError ? err.body.message : String(err);
      setState({ ...state, submitting: false, error: msg });
    }
  }, [connection, state, onImported]);

  const handleBack = useCallback(() => {
    setState({ step: "connect", submitting: false, error: null });
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="relational-extraction-title"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[720px] max-h-[85vh] flex flex-col">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close relational extraction"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 id="relational-extraction-title" className="text-lg font-semibold text-gray-900">
            Extract Ontology from Relational Database
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {state.step === "connect" &&
              "Connect to a relational database and reverse-engineer its tables, columns, and foreign keys into a new AOE ontology."}
            {state.step === "preview" &&
              `Discovered ${state.preview.table_count} table(s) (${state.preview.view_count} view(s)) and ${state.preview.foreign_key_count} foreign key(s) on ${state.preview.db_label}. Review, then extract.`}
            {state.step === "result" && "Extraction completed."}
          </p>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1">
          {state.step === "connect" && (
            <ConnectStep
              connection={connection}
              onChange={setConnection}
              submitting={state.submitting}
              error={state.error}
              onSubmit={handlePreview}
            />
          )}
          {state.step === "preview" && (
            <PreviewStep
              preview={state.preview}
              extractConstraints={state.extractConstraints}
              imports={state.imports}
              registry={registry}
              submitting={state.submitting}
              error={state.error}
              onToggleConstraints={(v) =>
                state.step === "preview" && setState({ ...state, extractConstraints: v })
              }
              onToggleImport={(id) => {
                if (state.step !== "preview") return;
                const next = new Set(state.imports);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                setState({ ...state, imports: next });
              }}
            />
          )}
          {state.step === "result" && <ResultStep result={state.result} />}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          {state.step === "connect" && (
            <>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handlePreview}
                disabled={state.submitting}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                {state.submitting ? "Connecting…" : "Connect & Preview"}
              </button>
            </>
          )}
          {state.step === "preview" && (
            <>
              <button
                type="button"
                onClick={handleBack}
                disabled={state.submitting}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:cursor-not-allowed"
              >
                Back
              </button>
              <button
                type="button"
                onClick={handleExtract}
                disabled={state.submitting || state.preview.table_count === 0}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                {state.submitting ? "Extracting…" : "Extract & Import"}
              </button>
            </>
          )}
          {state.step === "result" && (
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step subviews
// ---------------------------------------------------------------------------

interface ConnectStepProps {
  connection: ConnectionConfig;
  onChange: (next: ConnectionConfig) => void;
  submitting: boolean;
  error: string | null;
  onSubmit: () => void;
}

function ConnectStep({ connection, onChange, submitting, error, onSubmit }: ConnectStepProps) {
  const activeSource = SOURCE_TYPES.find((s) => s.id === connection.source_type);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) onSubmit();
      }}
      className="space-y-4"
      data-testid="relational-extraction-connect-step"
    >
      <Field label="Source type" htmlFor="re-source-type">
        <select
          id="re-source-type"
          value={connection.source_type}
          onChange={(e) => onChange({ ...connection, source_type: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {SOURCE_TYPES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Connection string / path" htmlFor="re-url">
        <input
          id="re-url"
          type="text"
          value={connection.url}
          onChange={(e) => onChange({ ...connection, url: e.target.value })}
          placeholder={activeSource?.urlHint ?? ""}
          autoComplete="off"
          required
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Schema / namespace" htmlFor="re-schema">
          <input
            id="re-schema"
            type="text"
            value={connection.schema_name}
            onChange={(e) => onChange({ ...connection, schema_name: e.target.value })}
            placeholder="public"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </Field>
        <Field label="DB label (optional)" htmlFor="re-db-label">
          <input
            id="re-db-label"
            type="text"
            value={connection.db_label}
            onChange={(e) => onChange({ ...connection, db_label: e.target.value })}
            placeholder="auto"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </Field>
      </div>

      <div className="pt-3 border-t border-gray-100">
        <p className="text-xs font-medium text-gray-700 mb-2">New ontology (optional)</p>
        <Field label="Display name" htmlFor="re-ont-label">
          <input
            id="re-ont-label"
            type="text"
            value={connection.ontology_label}
            onChange={(e) => onChange({ ...connection, ontology_label: e.target.value })}
            placeholder={`Schema: ${connection.db_label || "<db>"}`}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </Field>
        <p className="text-[11px] text-gray-500 mt-1">
          A registry ID is auto-generated. Leave Display name blank for the default.
        </p>
      </div>

      {error && (
        <div
          role="alert"
          data-testid="relational-extraction-connect-error"
          className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {/* Visually hidden submit so Enter triggers preview when focus is in a field. */}
      <button type="submit" className="sr-only" disabled={submitting} aria-hidden>
        Submit
      </button>
    </form>
  );
}

interface PreviewStepProps {
  preview: PreviewResponse;
  extractConstraints: boolean;
  imports: Set<string>;
  registry: RegistryEntry[];
  submitting: boolean;
  error: string | null;
  onToggleConstraints: (v: boolean) => void;
  onToggleImport: (id: string) => void;
}

function PreviewStep({
  preview,
  extractConstraints,
  imports,
  registry,
  submitting,
  error,
  onToggleConstraints,
  onToggleImport,
}: PreviewStepProps) {
  const summary = useMemo(() => summarizeRelationalExtraction(preview), [preview]);

  return (
    <div className="space-y-5" data-testid="relational-extraction-preview-step">
      <div
        data-testid="relational-extraction-preview-summary"
        className="bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2.5 text-sm text-indigo-900"
      >
        Will create <span className="font-mono font-semibold">{summary.classes}</span> classes,{" "}
        <span className="font-mono font-semibold">{summary.datatypeProperties}</span> datatype
        properties, and{" "}
        <span className="font-mono font-semibold">{summary.objectProperties}</span> object
        properties.
      </div>

      <section>
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
          Tables ({preview.table_count})
        </h3>
        {preview.tables.length === 0 ? (
          <p className="text-xs text-gray-500 italic">
            No tables found in schema <span className="font-mono">{preview.schema_name}</span>.
          </p>
        ) : (
          <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-y-auto">
            {preview.tables.map((t) => (
              <li
                key={t.name}
                data-testid={`relational-extraction-table-${t.name}`}
                className="px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900 truncate">{t.name}</span>
                  {t.is_view && (
                    <span className="text-[10px] uppercase tracking-wide text-amber-700 bg-amber-50 border border-amber-200 rounded px-1">
                      view
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-gray-500">
                  {t.column_count} column(s)
                  {t.primary_key.length > 0 && (
                    <>
                      {" · PK: "}
                      <span className="font-mono">{t.primary_key.join(", ")}</span>
                    </>
                  )}
                  {t.foreign_keys.length > 0 && ` · ${t.foreign_keys.length} FK`}
                </p>
                {t.foreign_keys.length > 0 && (
                  <p className="text-[11px] text-gray-400 font-mono truncate mt-0.5">
                    {t.foreign_keys
                      .map(
                        (fk) =>
                          `${fk.columns.join("|")} → ${fk.foreign_table}(${fk.foreign_columns.join("|")})`,
                      )
                      .join("  ·  ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
          Constraints
        </h3>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={extractConstraints}
            onChange={(e) => onToggleConstraints(e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
          Emit SHACL from NOT NULL / UNIQUE / CHECK-enum constraints
        </label>
      </section>

      {registry.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
            Import existing ontologies (optional)
          </h3>
          <p className="text-[11px] text-gray-500 mb-2">
            Selected ontologies become <code>owl:imports</code> on the new ontology.
          </p>
          <ul className="border border-gray-200 rounded-lg max-h-40 overflow-y-auto divide-y divide-gray-100">
            {registry.map((r) => (
              <li
                key={r._key}
                data-testid={`relational-extraction-import-${r._key}`}
                className="px-3 py-1.5 flex items-center gap-2"
              >
                <input
                  type="checkbox"
                  checked={imports.has(r._key)}
                  onChange={() => onToggleImport(r._key)}
                  aria-label={`Import ${r.name || r._key}`}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-sm text-gray-800 truncate">{r.name || r._key}</span>
                <span className="text-[10px] text-gray-400 font-mono ml-auto">{r._key}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {error && (
        <div
          role="alert"
          data-testid="relational-extraction-preview-error"
          className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {submitting && (
        <p className="text-xs text-indigo-600 italic">
          Extracting — introspecting the schema, mapping to OWL/SHACL, and importing.
        </p>
      )}
    </div>
  );
}

interface ResultStepProps {
  result: ExtractResponse;
}

function ResultStep({ result }: ResultStepProps) {
  const stats = result.import_stats as
    | { classes?: number; properties?: number; edges?: number }
    | undefined;
  return (
    <div className="space-y-4" data-testid="relational-extraction-result-step">
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
        <p className="text-sm font-semibold text-emerald-800">
          Extraction completed successfully.
        </p>
        <p className="text-xs text-emerald-700 mt-1">
          New ontology: <span className="font-mono">{result.ontology_id}</span>
        </p>
      </div>

      <dl className="text-sm space-y-1.5">
        <Stat label="Run ID" value={result.run_id} mono />
        <Stat label="Status" value={result.status} />
        {stats?.classes != null && <Stat label="Classes" value={String(stats.classes)} />}
        {stats?.properties != null && (
          <Stat label="Properties" value={String(stats.properties)} />
        )}
        {stats?.edges != null && <Stat label="Edges" value={String(stats.edges)} />}
        <Stat label="Provenance stamped" value={`${result.provenance_stamped} class(es)`} />
      </dl>

      <p className="text-xs text-gray-500">
        The new ontology has been added to the library and is now open in the workspace.
        Right-click its row in the explorer for further actions.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-xs font-medium text-gray-700 mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}

function Stat({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-xs text-gray-500 w-32 flex-shrink-0">{label}</dt>
      <dd className={`text-sm text-gray-900 ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
