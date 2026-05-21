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

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api-client";
import type { OntologyConstraint } from "@/types/timeline";

interface ClassConstraintsSectionProps {
  ontologyId: string;
  classKey: string;
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
      };
      byKey.set(key, g);
    }
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

  useEffect(() => {
    let cancelled = false;

    async function fetchConstraints() {
      setLoading(true);
      setError(null);
      try {
        const classId = `ontology_classes/${classKey}`;
        const url =
          `/api/v1/ontology/library/${ontologyId}/constraints` +
          `?class_id=${encodeURIComponent(classId)}`;
        const res = await api.get<ConstraintsResponse>(url);
        if (!cancelled) {
          setConstraints(res.constraints);
        }
      } catch (err) {
        if (!cancelled) {
          // Constraint listing is non-critical; a 404 / 500 here should
          // not blank the rest of the panel. Surface a short message
          // inline so the curator knows something didn't load.
          setError(
            err instanceof ApiError
              ? err.body.message
              : "Failed to load constraints",
          );
          setConstraints([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchConstraints();
    return () => {
      cancelled = true;
    };
  }, [ontologyId, classKey]);

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

      <div className="space-y-2">
        {groups.map((g) => (
          <PropertyConstraintRow key={g.property_uri} group={g} />
        ))}
      </div>
    </div>
  );
}

function PropertyConstraintRow({ group }: { group: PropertyGroup }) {
  const propertyDisplay = group.property_label || group.property_uri;
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
