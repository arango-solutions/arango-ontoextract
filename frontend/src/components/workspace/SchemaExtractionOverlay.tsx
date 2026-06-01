"use client";

/**
 * Schema Extraction overlay (Stream 5 PR 2 -- S.11 + S.12).
 *
 * Lets a curator point AOE at any ArangoDB instance, discover its named
 * graphs + loose collections, optionally pick which graphs to walk +
 * which existing ontologies to ``owl:imports``, and commit the
 * reverse-engineered ontology to the AOE registry.
 *
 * Per ``ui-architecture.mdc``:
 *  - Overlay over the workspace canvas, never a new route (rule 9).
 *  - Opened from the canvas right-click menu ("Extract from ArangoDB…",
 *    near "Browse Standard Catalog…" -- both are add-an-ontology
 *    actions). Esc + × close.
 *  - Credentials live in form state only, never persisted; the backend
 *    matches this by accepting POST (not GET) for both
 *    ``/schema/graphs`` and ``/schema/extract`` so passwords never leak
 *    via URLs / referrer headers.
 *  - The "Extract from ArangoDB…" verb has no canonical icon in
 *    ``ui-architecture.mdc`` §23, so we use 🗄 (file cabinet) for
 *    "structured data store". When/if the canonical table grows an
 *    entry for "extract from external source", swap here.
 *
 * Three-step state machine, all in one component (state, not routes):
 *
 *   ┌──────────┐    discover    ┌──────────┐    extract    ┌────────┐
 *   │ connect  │ ─────────────► │ preview  │ ────────────► │ result │
 *   │ (form)   │                │ (graphs) │               │        │
 *   └──────────┘ ◄────────────  └──────────┘               └────────┘
 *                   "Back"
 *
 * Backend endpoints (shipped in PR 1):
 *
 *   POST /api/v1/ontology/schema/graphs    -> topology discovery
 *   POST /api/v1/ontology/schema/extract   -> commit (TTL gen + import + provenance)
 *
 * The preview step shows topology only -- not the full proposed TTL --
 * because the datatype-property names come from per-collection field
 * sampling that only runs at extract time. A future iteration can add
 * a "dry-run extract" backend endpoint that returns the TTL + URI map
 * without writing to the registry; for v1 the topology + a count
 * summary ("N classes, M object properties, sampling enabled") is the
 * commit gate.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Wire types -- mirror app/services/schema_extraction.py and the
// ``/schema/graphs`` + ``/schema/extract`` responses in app/api/ontology.py.
// ---------------------------------------------------------------------------

interface EdgeDefinition {
  edge_collection: string;
  from_vertex_collections: string[];
  to_vertex_collections: string[];
}

interface GraphTopology {
  name: string;
  edge_definitions: EdgeDefinition[];
  vertex_collections: string[];
  orphan_collections: string[];
}

interface LooseCollection {
  name: string;
  type: "document" | "edge";
  count: number | null;
}

interface GraphsResponse {
  target_host: string;
  target_db: string;
  graphs: GraphTopology[];
  loose_collections: LooseCollection[];
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
// Connection form state. Kept on a single object so the back-from-preview
// button can restore everything the user typed; the extract step also
// reuses these values to POST /schema/extract.
// ---------------------------------------------------------------------------

interface ConnectionConfig {
  target_host: string;
  target_db: string;
  target_user: string;
  target_password: string;
  verify_tls: boolean;
  ontology_label: string;
  ontology_id: string;
}

const EMPTY_CONNECTION: ConnectionConfig = {
  target_host: "http://localhost:8530",
  target_db: "",
  target_user: "root",
  target_password: "",
  verify_tls: true,
  ontology_label: "",
  ontology_id: "",
};

// ---------------------------------------------------------------------------
// Step state. We keep the topology + selections on the preview step so the
// commit step has everything it needs to build the SchemaExtractionConfig
// body without re-asking the backend.
// ---------------------------------------------------------------------------

type StepState =
  | { step: "connect"; submitting: boolean; error: string | null }
  | {
      step: "preview";
      topology: GraphsResponse;
      selectedGraphs: Set<string>;
      includeLoose: boolean;
      sampleFields: boolean;
      fieldSampleLimit: number;
      imports: Set<string>;
      submitting: boolean;
      error: string | null;
    }
  | { step: "result"; result: ExtractResponse };

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  onClose: () => void;
  /** Fired once on a successful extract so the parent can refresh the
   *  library and switch to the newly created ontology. Receives the
   *  AOE registry key of the new ontology. */
  onImported: (newOntologyId: string) => void;
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests).
// ---------------------------------------------------------------------------

/** Count classes + object properties that *will* be created given the
 *  user's selections. Pure -- exported so tests can pin the count math
 *  without rendering. */
export function summarizeExtraction(
  topology: GraphsResponse,
  selectedGraphs: Set<string>,
  includeLoose: boolean,
): { classes: number; objectProperties: number; sampledCollections: number } {
  const classes = new Set<string>();
  const objectProperties = new Set<string>();
  const docCollections = new Set<string>();
  const allEdgesInGraphs = new Set<string>();
  const allVerticesInGraphs = new Set<string>();

  for (const g of topology.graphs) {
    const selected = selectedGraphs.has(g.name);
    if (selected) {
      for (const ed of g.edge_definitions) {
        objectProperties.add(ed.edge_collection);
        allEdgesInGraphs.add(ed.edge_collection);
        for (const c of ed.from_vertex_collections) {
          classes.add(c);
          allVerticesInGraphs.add(c);
        }
        for (const c of ed.to_vertex_collections) {
          classes.add(c);
          allVerticesInGraphs.add(c);
        }
      }
      for (const c of g.orphan_collections) {
        classes.add(c);
        allVerticesInGraphs.add(c);
      }
    } else {
      // Even when a graph is unselected, its edges/vertices are still
      // "owned" by a named graph so they won't reappear as loose. Track
      // them so we don't double-count.
      for (const ed of g.edge_definitions) {
        allEdgesInGraphs.add(ed.edge_collection);
        for (const c of ed.from_vertex_collections) {
          allVerticesInGraphs.add(c);
        }
        for (const c of ed.to_vertex_collections) {
          allVerticesInGraphs.add(c);
        }
      }
      for (const c of g.orphan_collections) {
        allVerticesInGraphs.add(c);
      }
    }
  }

  if (includeLoose) {
    for (const lc of topology.loose_collections) {
      if (lc.type === "edge") {
        objectProperties.add(lc.name);
      } else {
        classes.add(lc.name);
      }
    }
  }

  // Datatype properties are sampled only from document collections that
  // ended up as classes (edges don't get field sampling because we
  // can't put `rdfs:domain` on a property and an edge sensibly here).
  for (const c of classes) {
    if (!allEdgesInGraphs.has(c)) {
      docCollections.add(c);
    }
  }

  return {
    classes: classes.size,
    objectProperties: objectProperties.size,
    sampledCollections: docCollections.size,
  };
}

/** Trim each connection field and reject the obvious bad shapes before
 *  hitting the network. Returns ``null`` when valid, otherwise the
 *  first user-visible error message. Pure -- exported for tests. */
export function validateConnection(c: ConnectionConfig): string | null {
  if (!c.target_host.trim()) return "Host is required.";
  try {
    const url = new URL(c.target_host);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "Host must use http:// or https:// scheme.";
    }
  } catch {
    return "Host is not a valid URL.";
  }
  if (!c.target_db.trim()) return "Database name is required.";
  if (!c.target_user.trim()) return "Username is required.";
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SchemaExtractionOverlay({ onClose, onImported }: Props) {
  const [connection, setConnection] = useState<ConnectionConfig>(EMPTY_CONNECTION);
  const [state, setState] = useState<StepState>({
    step: "connect",
    submitting: false,
    error: null,
  });
  // Existing AOE ontologies the curator may pick as `owl:imports` for
  // the new ontology. Fetched lazily on entering the preview step.
  const [registry, setRegistry] = useState<RegistryEntry[]>([]);

  // Esc closes the overlay. We intentionally do NOT consume Esc on the
  // preview step to "go back" because the user might have a half-filled
  // form they want to keep -- explicit "Back" button is safer.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // ---------------------------------------------------------------------
  // Step 1 → 2: discover
  // ---------------------------------------------------------------------

  const handleDiscover = useCallback(async () => {
    const validationError = validateConnection(connection);
    if (validationError) {
      setState({ step: "connect", submitting: false, error: validationError });
      return;
    }
    setState({ step: "connect", submitting: true, error: null });
    try {
      const topology = await api.post<GraphsResponse>(
        "/api/v1/ontology/schema/graphs",
        {
          target_host: connection.target_host.trim(),
          target_db: connection.target_db.trim(),
          target_user: connection.target_user.trim(),
          target_password: connection.target_password,
          verify_tls: connection.verify_tls,
        },
      );
      // Default: every discovered graph selected, loose collections on.
      const selectedGraphs = new Set(topology.graphs.map((g) => g.name));
      setState({
        step: "preview",
        topology,
        selectedGraphs,
        includeLoose: true,
        sampleFields: true,
        fieldSampleLimit: 10,
        imports: new Set(),
        submitting: false,
        error: null,
      });
      // Fire-and-forget registry fetch so the imports picker has data.
      // A failure here just leaves the picker empty -- the user can
      // still extract without imports.
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

  // ---------------------------------------------------------------------
  // Step 2 → 3: extract
  // ---------------------------------------------------------------------

  const handleExtract = useCallback(async () => {
    if (state.step !== "preview") return;
    setState({ ...state, submitting: true, error: null });
    try {
      const result = await api.post<ExtractResponse>(
        "/api/v1/ontology/schema/extract",
        {
          target_host: connection.target_host.trim(),
          target_db: connection.target_db.trim(),
          target_user: connection.target_user.trim(),
          target_password: connection.target_password,
          verify_tls: connection.verify_tls,
          // ``null`` means "walk all graphs" on the backend; passing
          // the empty list would walk *zero* graphs, which is almost
          // certainly not the user's intent if they ended up on the
          // preview step. Normalise here so the wire shape is precise.
          graph_names:
            state.selectedGraphs.size === state.topology.graphs.length
              ? null
              : Array.from(state.selectedGraphs),
          include_loose: state.includeLoose,
          sample_fields: state.sampleFields,
          field_sample_limit: state.fieldSampleLimit,
          imports: Array.from(state.imports),
          ontology_label: connection.ontology_label.trim() || undefined,
          ontology_id: connection.ontology_id.trim() || undefined,
        },
      );
      setState({ step: "result", result });
      onImported(result.ontology_id);
    } catch (err) {
      const msg = err instanceof ApiError ? err.body.message : String(err);
      setState({ ...state, submitting: false, error: msg });
    }
  }, [connection, state, onImported]);

  // ---------------------------------------------------------------------
  // Step 2 -> 1: back (preserves connection, discards topology selections
  // because they only make sense in the context of the discovered shape).
  // ---------------------------------------------------------------------

  const handleBack = useCallback(() => {
    setState({ step: "connect", submitting: false, error: null });
  }, []);

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="schema-extraction-title"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[720px] max-h-[85vh] flex flex-col">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close schema extraction"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 id="schema-extraction-title" className="text-lg font-semibold text-gray-900">
            Extract Ontology from ArangoDB
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {state.step === "connect" &&
              "Connect to an external ArangoDB and reverse-engineer its named graphs + collections into a new AOE ontology."}
            {state.step === "preview" &&
              `Discovered ${state.topology.graphs.length} named graph(s) and ${state.topology.loose_collections.length} loose collection(s) on ${state.topology.target_db}. Pick what to extract.`}
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
              onSubmit={handleDiscover}
            />
          )}
          {state.step === "preview" && (
            <PreviewStep
              topology={state.topology}
              selectedGraphs={state.selectedGraphs}
              includeLoose={state.includeLoose}
              sampleFields={state.sampleFields}
              fieldSampleLimit={state.fieldSampleLimit}
              imports={state.imports}
              registry={registry}
              submitting={state.submitting}
              error={state.error}
              onToggleGraph={(name) => {
                if (state.step !== "preview") return;
                const next = new Set(state.selectedGraphs);
                if (next.has(name)) next.delete(name);
                else next.add(name);
                setState({ ...state, selectedGraphs: next });
              }}
              onToggleLoose={(v) =>
                state.step === "preview" && setState({ ...state, includeLoose: v })
              }
              onToggleSample={(v) =>
                state.step === "preview" && setState({ ...state, sampleFields: v })
              }
              onSampleLimit={(v) =>
                state.step === "preview" && setState({ ...state, fieldSampleLimit: v })
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
                onClick={handleDiscover}
                disabled={state.submitting}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                {state.submitting ? "Connecting…" : "Connect & Discover"}
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
                disabled={state.submitting || state.selectedGraphs.size + (state.includeLoose ? state.topology.loose_collections.length : 0) === 0}
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
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) onSubmit();
      }}
      className="space-y-4"
      data-testid="schema-extraction-connect-step"
    >
      <Field label="Host" htmlFor="se-host">
        <input
          id="se-host"
          type="text"
          value={connection.target_host}
          onChange={(e) => onChange({ ...connection, target_host: e.target.value })}
          placeholder="http://localhost:8530"
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </Field>
      <Field label="Database" htmlFor="se-db">
        <input
          id="se-db"
          type="text"
          value={connection.target_db}
          onChange={(e) => onChange({ ...connection, target_db: e.target.value })}
          placeholder="_system"
          required
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Username" htmlFor="se-user">
          <input
            id="se-user"
            type="text"
            value={connection.target_user}
            onChange={(e) => onChange({ ...connection, target_user: e.target.value })}
            autoComplete="off"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </Field>
        <Field label="Password" htmlFor="se-password">
          <input
            id="se-password"
            type="password"
            value={connection.target_password}
            onChange={(e) => onChange({ ...connection, target_password: e.target.value })}
            autoComplete="off"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={connection.verify_tls}
          onChange={(e) => onChange({ ...connection, verify_tls: e.target.checked })}
          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
        Verify TLS certificate (uncheck for self-signed dev hosts)
      </label>

      <div className="pt-3 border-t border-gray-100">
        <p className="text-xs font-medium text-gray-700 mb-2">
          New ontology (optional)
        </p>
        <Field label="Display name" htmlFor="se-ont-label">
          <input
            id="se-ont-label"
            type="text"
            value={connection.ontology_label}
            onChange={(e) => onChange({ ...connection, ontology_label: e.target.value })}
            placeholder={`Schema: ${connection.target_db || "<db>"}`}
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
          data-testid="schema-extraction-connect-error"
          className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {/* Visually hidden submit so Enter triggers discover when focus is in a field. */}
      <button type="submit" className="sr-only" disabled={submitting} aria-hidden>
        Submit
      </button>
    </form>
  );
}

interface PreviewStepProps {
  topology: GraphsResponse;
  selectedGraphs: Set<string>;
  includeLoose: boolean;
  sampleFields: boolean;
  fieldSampleLimit: number;
  imports: Set<string>;
  registry: RegistryEntry[];
  submitting: boolean;
  error: string | null;
  onToggleGraph: (name: string) => void;
  onToggleLoose: (v: boolean) => void;
  onToggleSample: (v: boolean) => void;
  onSampleLimit: (v: number) => void;
  onToggleImport: (id: string) => void;
}

function PreviewStep({
  topology,
  selectedGraphs,
  includeLoose,
  sampleFields,
  fieldSampleLimit,
  imports,
  registry,
  submitting,
  error,
  onToggleGraph,
  onToggleLoose,
  onToggleSample,
  onSampleLimit,
  onToggleImport,
}: PreviewStepProps) {
  const summary = useMemo(
    () => summarizeExtraction(topology, selectedGraphs, includeLoose),
    [topology, selectedGraphs, includeLoose],
  );

  return (
    <div className="space-y-5" data-testid="schema-extraction-preview-step">
      {/* Summary line drives the commit gate -- when nothing is selected,
       *  the bottom "Extract & Import" button is disabled. */}
      <div
        data-testid="schema-extraction-preview-summary"
        className="bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2.5 text-sm text-indigo-900"
      >
        Will create{" "}
        <span className="font-mono font-semibold">{summary.classes}</span> classes
        and{" "}
        <span className="font-mono font-semibold">{summary.objectProperties}</span>{" "}
        object properties
        {sampleFields && summary.sampledCollections > 0 && (
          <>
            , plus datatype properties sampled from{" "}
            <span className="font-mono font-semibold">{summary.sampledCollections}</span>{" "}
            document collection(s)
          </>
        )}
        .
      </div>

      <section>
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
          Named graphs ({topology.graphs.length})
        </h3>
        {topology.graphs.length === 0 ? (
          <p className="text-xs text-gray-500 italic">
            No named graphs on this database. The extraction will use loose
            collections only.
          </p>
        ) : (
          <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100">
            {topology.graphs.map((g) => {
              const checked = selectedGraphs.has(g.name);
              const edgeCount = g.edge_definitions.length;
              const vertexCount = g.vertex_collections.length;
              return (
                <li
                  key={g.name}
                  data-testid={`schema-extraction-graph-${g.name}`}
                  className="px-3 py-2.5 flex items-start gap-3"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleGraph(g.name)}
                    aria-label={`Include graph ${g.name}`}
                    className="mt-1 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-gray-900 truncate">
                      {g.name}
                    </p>
                    <p className="text-[11px] text-gray-500">
                      {vertexCount} vertex collection(s), {edgeCount} edge
                      definition(s)
                    </p>
                    {edgeCount > 0 && (
                      <p className="text-[11px] text-gray-400 font-mono truncate mt-0.5">
                        {g.edge_definitions
                          .map(
                            (ed) =>
                              `${ed.from_vertex_collections.join("|")} -[${ed.edge_collection}]→ ${ed.to_vertex_collections.join("|")}`,
                          )
                          .join("  ·  ")}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
          Loose collections ({topology.loose_collections.length})
        </h3>
        <label className="flex items-center gap-2 text-sm text-gray-700 mb-2">
          <input
            type="checkbox"
            checked={includeLoose}
            onChange={(e) => onToggleLoose(e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
          Include loose collections (not in any named graph)
        </label>
        {topology.loose_collections.length === 0 ? (
          <p className="text-xs text-gray-500 italic">No loose collections.</p>
        ) : (
          // ``aria-disabled`` belongs on the group container, not on the
          // ``<ul>`` (whose implicit ``role="list"`` doesn't support that
          // attribute -- caught by jsx-a11y/role-supports-aria-props).
          <div aria-disabled={!includeLoose}>
            <ul
              className={`text-xs text-gray-700 max-h-32 overflow-y-auto border border-gray-100 rounded ${includeLoose ? "" : "opacity-40"}`}
            >
              {topology.loose_collections.map((lc) => (
                <li
                  key={lc.name}
                  className="px-2 py-1 flex items-center justify-between border-b border-gray-50 last:border-b-0"
                >
                  <span className="font-mono">{lc.name}</span>
                  <span className="text-[10px] text-gray-400">
                    {lc.type === "edge" ? "edge" : "doc"}
                    {lc.count != null && ` · ${lc.count}`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section>
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
          Field sampling
        </h3>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={sampleFields}
            onChange={(e) => onToggleSample(e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
          Sample scalar fields to emit datatype properties
        </label>
        {sampleFields && (
          <div className="mt-2 flex items-center gap-3 text-xs text-gray-700">
            <label htmlFor="se-sample-limit">Documents per collection:</label>
            <input
              id="se-sample-limit"
              type="number"
              min={0}
              max={1000}
              value={fieldSampleLimit}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (!Number.isNaN(n) && n >= 0 && n <= 1000) onSampleLimit(n);
              }}
              className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <span className="text-[11px] text-gray-400">
              Higher = more accurate XSD types, slower extraction.
            </span>
          </div>
        )}
      </section>

      {registry.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
            Import existing ontologies (optional)
          </h3>
          <p className="text-[11px] text-gray-500 mb-2">
            Selected ontologies become <code>owl:imports</code> on the new
            ontology — useful for layering domain vocabularies on top of the
            extracted schema.
          </p>
          <ul className="border border-gray-200 rounded-lg max-h-40 overflow-y-auto divide-y divide-gray-100">
            {registry.map((r) => {
              const checked = imports.has(r._key);
              return (
                <li
                  key={r._key}
                  data-testid={`schema-extraction-import-${r._key}`}
                  className="px-3 py-1.5 flex items-center gap-2"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleImport(r._key)}
                    aria-label={`Import ${r.name || r._key}`}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-sm text-gray-800 truncate">
                    {r.name || r._key}
                  </span>
                  <span className="text-[10px] text-gray-400 font-mono ml-auto">
                    {r._key}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {error && (
        <div
          role="alert"
          data-testid="schema-extraction-preview-error"
          className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {submitting && (
        <p className="text-xs text-indigo-600 italic">
          Extracting — this may take a few seconds for small databases or several
          minutes for large ones (sampled documents per collection scales with
          extraction time).
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
    <div className="space-y-4" data-testid="schema-extraction-result-step">
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
        <Stat
          label="Provenance stamped"
          value={`${result.provenance_stamped} class(es)`}
        />
      </dl>

      <p className="text-xs text-gray-500">
        The new ontology has been added to the library and is now open in the
        workspace. Right-click its row in the explorer for further actions.
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
