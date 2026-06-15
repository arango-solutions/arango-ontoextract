"use client";

/**
 * ClassConstraintsSection -- Stream 3 PR 4.
 *
 * Renders the OWL restrictions + SHACL shapes that apply to one class,
 * grouped by property so a curator sees the unified picture: cardinality
 * bounds, value restrictions (datatype / class / hasValue / pattern /
 * nodeKind / sh:in enumeration), and severity (SHACL).
 *
 * Three source vocabularies feed the same row shape (PR 1 extraction,
 * PR 2 OWL import, PR 3 SHACL import). This component is the FIRST
 * UI surface where curators can see all three side-by-side. A source
 * pill on each constraint chip keeps provenance visible:
 *
 *  * "extracted"  -- LLM-emitted (PR 1)         -- purple
 *  * "owl"        -- owl:Restriction (PR 2)     -- blue
 *  * "shacl"      -- sh:PropertyShape (PR 3)    -- orange
 *
 * Backend contract: ``GET /api/v1/ontology/{id}/library/{id}/constraints``
 * with ``?class_id=ontology_classes/<key>`` returns one row per
 * (property, constraint kind). Cardinality rows for the same property
 * are grouped client-side into a combined "n..m" badge so a class with
 * both ``minCardinality 1`` AND ``maxCardinality 5`` shows as "1..5"
 * rather than two separate chips -- matches the rule engine's grouping
 * and is what a curator actually thinks about.
 */

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api-client";
import type { OntologyConstraint } from "@/types/timeline";

interface ClassConstraintsSectionProps {
  ontologyId: string;
  classKey: string;
}

/** Curator status of a constraint row; absent ``status`` is treated as pending. */
function constraintStatus(c: OntologyConstraint): "pending" | "approved" | "rejected" {
  const s = (c as { status?: string }).status;
  if (s === "approved" || s === "rejected") return s;
  return "pending";
}

interface ConstraintsResponse {
  ontology_id: string;
  constraints: OntologyConstraint[];
  total: number;
}

// ---------------------------------------------------------------------------
// Source / severity mapping
// ---------------------------------------------------------------------------

type SourceKey = "extracted" | "owl" | "shacl" | "unknown";

interface SourceMeta {
  label: string;
  /** Tailwind classes for a small pill. */
  classes: string;
  /** Long-form tooltip text explaining provenance. */
  title: string;
}

const SOURCE_META: Record<SourceKey, SourceMeta> = {
  extracted: {
    label: "extracted",
    classes: "bg-purple-50 text-purple-700 border-purple-200",
    title: "Extracted by LLM from source documents (Stream 3 PR 1).",
  },
  owl: {
    label: "OWL",
    classes: "bg-blue-50 text-blue-700 border-blue-200",
    title: "Imported from an owl:Restriction in the source ontology file (PR 2).",
  },
  shacl: {
    label: "SHACL",
    classes: "bg-orange-50 text-orange-700 border-orange-200",
    title: "Imported from a sh:PropertyShape in the source SHACL graph (PR 3).",
  },
  unknown: {
    label: "?",
    classes: "bg-gray-50 text-gray-600 border-gray-200",
    title: "Unknown source -- legacy row or unrecognized constraint_type.",
  },
};

/** Decide source for one constraint row from its provenance markers. */
function classifySource(c: OntologyConstraint): SourceKey {
  if (c.import_source === "owl_restriction") return "owl";
  if (c.import_source === "shacl_shape") return "shacl";
  if (c.extraction_run_id) return "extracted";
  // Fall back on constraint_type for legacy rows that lack provenance.
  if (c.constraint_type === "owl:Restriction") return "owl";
  if (
    c.constraint_type === "sh:PropertyShape" ||
    c.constraint_type === "sh:NodeShape"
  )
    return "shacl";
  return "unknown";
}

interface SeverityMeta {
  icon: string;
  classes: string;
  label: string;
}

/** SHACL severity glyph; ``null`` for non-SHACL constraints (no icon). */
function severityMeta(severity?: string): SeverityMeta | null {
  if (!severity) return null;
  switch (severity) {
    case "sh:Violation":
      return { icon: "⚠", classes: "text-red-600", label: "Violation" };
    case "sh:Warning":
      return { icon: "⚠", classes: "text-amber-600", label: "Warning" };
    case "sh:Info":
      return { icon: "ℹ", classes: "text-blue-600", label: "Info" };
    default:
      // Custom severity URI -- show a neutral marker rather than dropping it.
      return { icon: "●", classes: "text-gray-500", label: severity };
  }
}

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

const XSD_PREFIX = "http://www.w3.org/2001/XMLSchema#";

/**
 * Format a constraint value for display, applying minor humanisations:
 *
 *  * Strip the XSD namespace from datatypes -- "string" reads better
 *    than the full IRI in a chip the size of a thumbprint.
 *  * Render ``sh:in`` arrays as a comma-joined list.
 *  * Leave URIs that aren't recognized intact (they're already short
 *    enough to read in a tooltip).
 */
function formatValue(value: OntologyConstraint["restriction_value"]): string {
  if (value == null) return "—";
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "string" && value.startsWith(XSD_PREFIX)) {
    return value.slice(XSD_PREFIX.length);
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Cardinality grouping
// ---------------------------------------------------------------------------

const CARDINALITY_KINDS = new Set([
  "minCardinality",
  "maxCardinality",
  "cardinality",
  "sh:minCount",
  "sh:maxCount",
]);

interface PropertyGroup {
  property_uri: string;
  property_label: string;
  /** Combined "n..m" / "≥n" / "≤n" / "=n" bound text, or empty. */
  cardinalityBadge: string | null;
  /** All non-cardinality rows -- one chip per row. */
  chips: OntologyConstraint[];
  /** Sources represented in this group, for the property header pill stack. */
  sources: SourceKey[];
  /** Every raw row for this property (incl. the collapsed cardinality rows),
   *  so the curation "Manage" list can act on each constraint individually. */
  allRows: OntologyConstraint[];
}

/**
 * Group raw constraint rows by property and collapse cardinality rows
 * into a single badge so the curator sees ONE "1..5" instead of two
 * chips that they have to reason about together.
 *
 * Grouping mirrors ``_cardinality_violation`` in the rule engine, so
 * the UI displays exactly what the engine evaluates.
 */
export function groupConstraintsByProperty(
  rows: OntologyConstraint[],
): PropertyGroup[] {
  type Working = {
    property_uri: string;
    property_label: string;
    minBound?: number;
    maxBound?: number;
    exactBound?: number;
    chips: OntologyConstraint[];
    sources: Set<SourceKey>;
    allRows: OntologyConstraint[];
  };
  const byKey = new Map<string, Working>();

  for (const c of rows) {
    const key = c.property_uri;
    let g = byKey.get(key);
    if (g === undefined) {
      g = {
        property_uri: key,
        property_label: c.property_label || "",
        chips: [],
        sources: new Set(),
        allRows: [],
      };
      byKey.set(key, g);
    }
    g.allRows.push(c);
    // Keep the first non-empty label encountered -- the import path
    // always populates this, extraction may not.
    if (!g.property_label && c.property_label) {
      g.property_label = c.property_label;
    }
    g.sources.add(classifySource(c));

    if (
      CARDINALITY_KINDS.has(c.restriction_type) &&
      typeof c.restriction_value === "number"
    ) {
      const n = c.restriction_value;
      if (c.restriction_type === "cardinality") {
        // owl:cardinality N -- exactly N (rule engine expands to min==max==N).
        g.exactBound = n;
      } else if (
        c.restriction_type === "minCardinality" ||
        c.restriction_type === "sh:minCount"
      ) {
        // The strictest bound wins, matching the cross-vocab semantics
        // a curator would expect from "OWL says ≥1 AND SHACL says ≥2".
        g.minBound = g.minBound === undefined ? n : Math.max(g.minBound, n);
      } else {
        g.maxBound = g.maxBound === undefined ? n : Math.min(g.maxBound, n);
      }
    } else {
      g.chips.push(c);
    }
  }

  const out: PropertyGroup[] = [];
  for (const g of byKey.values()) {
    out.push({
      property_uri: g.property_uri,
      property_label: g.property_label,
      cardinalityBadge: formatCardinality(g),
      chips: g.chips,
      sources: Array.from(g.sources).sort(),
      allRows: g.allRows,
    });
  }
  // Stable display order: property label > URI fallback.
  out.sort((a, b) =>
    (a.property_label || a.property_uri).localeCompare(
      b.property_label || b.property_uri,
    ),
  );
  return out;
}

function formatCardinality(g: {
  minBound?: number;
  maxBound?: number;
  exactBound?: number;
}): string | null {
  if (g.exactBound !== undefined) {
    return `=${g.exactBound}`;
  }
  if (g.minBound !== undefined && g.maxBound !== undefined) {
    if (g.minBound === g.maxBound) return `=${g.minBound}`;
    return `${g.minBound}..${g.maxBound}`;
  }
  if (g.minBound !== undefined) return `≥${g.minBound}`;
  if (g.maxBound !== undefined) return `≤${g.maxBound}`;
  return null;
}

// ---------------------------------------------------------------------------
// Restriction-type human labels
// ---------------------------------------------------------------------------

const RESTRICTION_LABELS: Record<string, string> = {
  allValuesFrom: "all from",
  someValuesFrom: "some from",
  hasValue: "must be",
  "sh:datatype": "datatype",
  "sh:class": "class",
  "sh:hasValue": "must be",
  "sh:pattern": "pattern",
  "sh:nodeKind": "node kind",
  "sh:in": "one of",
};

function restrictionLabel(rtype: string): string {
  return RESTRICTION_LABELS[rtype] || rtype;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ClassConstraintsSection({
  ontologyId,
  classKey,
}: ClassConstraintsSectionProps) {
  const [constraints, setConstraints] = useState<OntologyConstraint[] | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Mutation-side state (curation actions). Kept separate from the load
  // error so a failed approve doesn't blank the constraint list.
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const refetch = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const classId = `ontology_classes/${classKey}`;
        const url =
          `/api/v1/ontology/library/${ontologyId}/constraints` +
          `?class_id=${encodeURIComponent(classId)}`;
        const res = await api.get<ConstraintsResponse>(url, { signal });
        if (!signal?.aborted) setConstraints(res.constraints);
      } catch (err) {
        if (signal?.aborted) return;
        // Constraint listing is non-critical; a 404 / 500 here should
        // not blank the rest of the panel. Surface a short message
        // inline so the curator knows something didn't load.
        setError(
          err instanceof ApiError ? err.body.message : "Failed to load constraints",
        );
        setConstraints([]);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [ontologyId, classKey],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refetch(controller.signal);
    return () => controller.abort();
  }, [refetch]);

  // Run one curation mutation, then refetch so the list reflects the new
  // temporal version (approve/edit change the row's _key; reject expires it).
  const runAction = useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      setBusyKey(key);
      setActionError(null);
      try {
        await fn();
        await refetch();
      } catch (err) {
        setActionError(
          err instanceof ApiError ? err.body.message : "Constraint action failed",
        );
      } finally {
        setBusyKey(null);
      }
    },
    [refetch],
  );

  const approve = useCallback(
    (key: string) =>
      runAction(key, () =>
        api.post(
          `/api/v1/ontology/${ontologyId}/constraints/${encodeURIComponent(key)}/approve`,
        ),
      ),
    [ontologyId, runAction],
  );

  const reject = useCallback(
    (key: string) =>
      runAction(key, () =>
        api.post(
          `/api/v1/ontology/${ontologyId}/constraints/${encodeURIComponent(key)}/reject`,
        ),
      ),
    [ontologyId, runAction],
  );

  const saveEdit = useCallback(
    (key: string, restriction_value: number | string, description: string) =>
      runAction(key, () =>
        api.put(
          `/api/v1/ontology/${ontologyId}/constraints/${encodeURIComponent(key)}`,
          { restriction_value, description },
        ),
      ),
    [ontologyId, runAction],
  );

  if (loading) {
    return (
      <div className="border-t border-gray-100 pt-3">
        <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          Constraints
        </dt>
        <p className="text-xs text-gray-400 animate-pulse">Loading...</p>
      </div>
    );
  }

  // Empty state: no constraints attached. Render nothing -- the parent
  // panel is busy enough; adding "0 constraints" everywhere would be noise.
  if (!error && (constraints == null || constraints.length === 0)) {
    return null;
  }

  const groups = constraints ? groupConstraintsByProperty(constraints) : [];

  return (
    <div className="border-t border-gray-100 pt-3">
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
        Constraints {constraints && `(${constraints.length})`}
      </dt>

      {error && (
        <p className="text-xs text-red-500 mb-2">{error}</p>
      )}
      {actionError && (
        <p className="text-xs text-red-500 mb-2">{actionError}</p>
      )}

      <div className="space-y-2">
        {groups.map((g) => (
          <PropertyConstraintRow
            key={g.property_uri}
            group={g}
            busyKey={busyKey}
            onApprove={approve}
            onReject={reject}
            onSaveEdit={saveEdit}
          />
        ))}
      </div>
    </div>
  );
}

interface RowActions {
  busyKey: string | null;
  onApprove: (key: string) => void;
  onReject: (key: string) => void;
  onSaveEdit: (key: string, value: number | string, description: string) => void;
}

function PropertyConstraintRow({
  group,
  busyKey,
  onApprove,
  onReject,
  onSaveEdit,
}: { group: PropertyGroup } & RowActions) {
  const propertyDisplay = group.property_label || group.property_uri;
  const [managing, setManaging] = useState(false);
  // Rows the curator can act on: those carrying a real _key (every
  // materialized row does). Pending rows surface an approve affordance.
  const manageable = group.allRows.filter((r) => r._key);
  return (
    <div className="bg-gray-50 rounded-md px-2.5 py-2">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span
          className="font-medium text-gray-800 text-xs truncate"
          title={group.property_uri}
        >
          {propertyDisplay}
        </span>
        {group.sources.map((s) => (
          <SourcePill key={s} source={s} />
        ))}
        {manageable.length > 0 && (
          <button
            type="button"
            onClick={() => setManaging((m) => !m)}
            className="ml-auto text-[10px] text-gray-400 hover:text-indigo-600"
            title="Approve, reject, or edit individual constraints"
          >
            {managing ? "Done" : "Manage"}
          </button>
        )}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {group.cardinalityBadge && (
          <span
            className="text-[11px] font-mono bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-700"
            title="Cardinality (collapsed from min/max/exact rows; rule-engine grouping)"
          >
            {group.cardinalityBadge}
          </span>
        )}
        {group.chips.map((c, idx) => (
          <ConstraintChip key={`${c.restriction_type}-${idx}`} constraint={c} />
        ))}
      </div>

      {managing && (
        <div className="mt-2 space-y-1 border-t border-gray-200 pt-2">
          {manageable.map((c) => (
            <ConstraintManageRow
              key={c._key}
              constraint={c}
              busy={busyKey === c._key}
              onApprove={onApprove}
              onReject={onReject}
              onSaveEdit={onSaveEdit}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** One editable/actionable line per raw constraint row in the Manage view. */
function ConstraintManageRow({
  constraint,
  busy,
  onApprove,
  onReject,
  onSaveEdit,
}: {
  constraint: OntologyConstraint;
  busy: boolean;
  onApprove: (key: string) => void;
  onReject: (key: string) => void;
  onSaveEdit: (key: string, value: number | string, description: string) => void;
}) {
  const key = constraint._key as string;
  const status = constraintStatus(constraint);
  const [editing, setEditing] = useState(false);
  const isNumeric = typeof constraint.restriction_value === "number";
  const [value, setValue] = useState(() => formatValue(constraint.restriction_value));
  const [description, setDescription] = useState(constraint.description ?? "");

  const statusPill =
    status === "approved"
      ? { text: "approved", cls: "bg-green-50 text-green-700 border-green-200" }
      : { text: "pending", cls: "bg-gray-100 text-gray-500 border-gray-200" };

  function commit() {
    const coerced = isNumeric ? Number(value) : value;
    if (isNumeric && Number.isNaN(coerced as number)) return;
    onSaveEdit(key, coerced, description);
    setEditing(false);
  }

  return (
    <div className="text-[11px] bg-white border border-gray-200 rounded px-2 py-1">
      <div className="flex items-center gap-1.5">
        <span className="text-gray-500">{restrictionLabel(constraint.restriction_type)}</span>
        {!editing && (
          <span className="font-mono text-gray-800 truncate max-w-[140px]">
            {formatValue(constraint.restriction_value)}
          </span>
        )}
        <span
          className={`text-[10px] uppercase tracking-wide px-1 py-px rounded border ${statusPill.cls}`}
        >
          {statusPill.text}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {!editing && status !== "approved" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onApprove(key)}
              className="text-green-600 hover:text-green-800 disabled:opacity-40"
              title="Approve constraint"
            >
              ✓
            </button>
          )}
          {!editing && (
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              className="text-gray-500 hover:text-indigo-700 disabled:opacity-40"
              title="Edit constraint"
            >
              ✎
            </button>
          )}
          {!editing && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onReject(key)}
              className="text-red-500 hover:text-red-700 disabled:opacity-40"
              title="Reject (remove) constraint"
            >
              ✗
            </button>
          )}
        </div>
      </div>

      {editing && (
        <div className="mt-1.5 space-y-1.5">
          <input
            type={isNumeric ? "number" : "text"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-label="Constraint value"
            className="w-full border border-gray-300 rounded px-1.5 py-0.5 text-[11px]"
          />
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            aria-label="Constraint description"
            className="w-full border border-gray-300 rounded px-1.5 py-0.5 text-[11px]"
          />
          <div className="flex items-center gap-2 justify-end">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={commit}
              className="px-2 py-0.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-40"
            >
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SourcePill({ source }: { source: SourceKey }) {
  const m = SOURCE_META[source];
  return (
    <span
      className={`text-[10px] uppercase tracking-wide px-1.5 py-px rounded border font-medium ${m.classes}`}
      title={m.title}
    >
      {m.label}
    </span>
  );
}

function ConstraintChip({ constraint }: { constraint: OntologyConstraint }) {
  const sev = severityMeta(constraint.severity);
  const valueDisplay = formatValue(constraint.restriction_value);
  return (
    <span
      className="text-[11px] inline-flex items-center gap-1 bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-700"
      title={constraint.description || constraint.restriction_type}
    >
      {sev && (
        <span
          className={sev.classes}
          role="img"
          aria-label={sev.label}
        >
          {sev.icon}
        </span>
      )}
      <span className="text-gray-500">{restrictionLabel(constraint.restriction_type)}</span>
      <span className="font-mono text-gray-800 truncate max-w-[180px]">
        {valueDisplay}
      </span>
    </span>
  );
}
