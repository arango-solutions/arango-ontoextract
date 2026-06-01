"use client";

/**
 * Schema diff overlay (Stream 5 PR 3 sub-B — S.5 frontend).
 *
 * Compares two ontologies via ``GET /api/v1/ontology/schema/diff`` and
 * renders added / removed / changed buckets for classes, properties, and
 * constraints. Opened from the ontology explorer context menu or the
 * canvas menu when an ontology is loaded (A = open ontology).
 *
 * Per ``ui-architecture.mdc``: overlay-not-route, Esc + × close.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import {
  constraintDiffLabel,
  entityDiffLabel,
  formatSchemaDiffSummaryLine,
  registryDisplayName,
  schemaDiffUrl,
  validateSchemaDiffSelection,
  type RegistryOntologyOption,
  type SchemaDiffChangedConstraintRow,
  type SchemaDiffChangedEntityRow,
  type SchemaDiffEntityRow,
  type SchemaDiffResponse,
} from "@/lib/schemaDiffHelpers";

export interface SchemaDiffOverlayProps {
  ontologyAKey: string;
  ontologyAName: string;
  onClose: () => void;
}

type AccordionKey = "classes" | "properties" | "constraints";

export default function SchemaDiffOverlay({
  ontologyAKey,
  ontologyAName,
  onClose,
}: SchemaDiffOverlayProps) {
  const [registry, setRegistry] = useState<RegistryOntologyOption[]>([]);
  const [ontologyBKey, setOntologyBKey] = useState("");
  const [diff, setDiff] = useState<SchemaDiffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSections, setOpenSections] = useState<Record<AccordionKey, boolean>>({
    classes: true,
    properties: false,
    constraints: false,
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ data: RegistryOntologyOption[] }>("/api/v1/ontology/library?limit=100")
      .then((res) => {
        if (cancelled) return;
        const rows = (res.data ?? []).filter((r) => r._key !== ontologyAKey);
        setRegistry(rows);
        setOntologyBKey((prev) => {
          if (prev && prev !== ontologyAKey && rows.some((r) => r._key === prev)) return prev;
          return rows[0]?._key ?? "";
        });
      })
      .catch(() => {
        if (!cancelled) setRegistry([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ontologyAKey]);

  const handleCompare = useCallback(async () => {
    const validation = validateSchemaDiffSelection(ontologyAKey, ontologyBKey);
    if (validation) {
      setError(validation);
      setDiff(null);
      return;
    }
    setLoading(true);
    setError(null);
    setDiff(null);
    try {
      const result = await api.get<SchemaDiffResponse>(schemaDiffUrl(ontologyAKey, ontologyBKey));
      setDiff(result);
      setOpenSections({
        classes: result.summary.classes_added + result.summary.classes_removed + result.summary.classes_changed > 0,
        properties:
          result.summary.properties_added +
            result.summary.properties_removed +
            result.summary.properties_changed >
          0,
        constraints:
          result.summary.constraints_added +
            result.summary.constraints_removed +
            result.summary.constraints_changed >
          0,
      });
    } catch (err) {
      const msg = err instanceof ApiError ? err.body.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [ontologyAKey, ontologyBKey]);

  const summaryLine = useMemo(
    () => (diff ? formatSchemaDiffSummaryLine(diff.summary) : null),
    [diff],
  );

  const toggleSection = (key: AccordionKey) => {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="schema-diff-title"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      data-testid="schema-diff-overlay"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[760px] max-h-[85vh] flex flex-col">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close schema diff"
          data-testid="schema-diff-close"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 id="schema-diff-title" className="text-lg font-semibold text-gray-900">
            Compare Schema Evolution
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            Diff classes, properties, and SHACL constraints between two ontology snapshots.
          </p>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Before (A)">
              <div className="text-sm font-medium text-gray-900" data-testid="schema-diff-ontology-a">
                {ontologyAName}
              </div>
              <div className="text-xs text-gray-500 font-mono mt-0.5">{ontologyAKey}</div>
            </Field>
            <Field label="After (B)">
              <select
                id="schema-diff-ontology-b"
                value={ontologyBKey}
                onChange={(e) => setOntologyBKey(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                data-testid="schema-diff-ontology-b-select"
              >
                <option value="">Select ontology…</option>
                {registry.map((row) => (
                  <option key={row._key} value={row._key}>
                    {registryDisplayName(row)}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {error && (
            <p className="text-sm text-red-600" data-testid="schema-diff-error" role="alert">
              {error}
            </p>
          )}

          {diff?.provenance.warning && (
            <div
              className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              data-testid="schema-diff-provenance-warning"
            >
              {diff.provenance.warning}
            </div>
          )}

          {summaryLine && (
            <p className="text-sm text-gray-700" data-testid="schema-diff-summary-line">
              {summaryLine}
            </p>
          )}

          {diff && (
            <div className="space-y-2">
              <DiffAccordion
                title="Classes"
                counts={[
                  diff.summary.classes_added,
                  diff.summary.classes_removed,
                  diff.summary.classes_changed,
                ]}
                open={openSections.classes}
                onToggle={() => toggleSection("classes")}
                testId="schema-diff-section-classes"
              >
                <EntityBucket
                  added={diff.classes.added}
                  removed={diff.classes.removed}
                  changed={diff.classes.changed}
                />
              </DiffAccordion>
              <DiffAccordion
                title="Properties"
                counts={[
                  diff.summary.properties_added,
                  diff.summary.properties_removed,
                  diff.summary.properties_changed,
                ]}
                open={openSections.properties}
                onToggle={() => toggleSection("properties")}
                testId="schema-diff-section-properties"
              >
                <EntityBucket
                  added={diff.properties.added}
                  removed={diff.properties.removed}
                  changed={diff.properties.changed}
                />
              </DiffAccordion>
              <DiffAccordion
                title="Constraints"
                counts={[
                  diff.summary.constraints_added,
                  diff.summary.constraints_removed,
                  diff.summary.constraints_changed,
                ]}
                open={openSections.constraints}
                onToggle={() => toggleSection("constraints")}
                testId="schema-diff-section-constraints"
              >
                <ConstraintBucket
                  added={diff.constraints.added}
                  removed={diff.constraints.removed}
                  changed={diff.constraints.changed}
                />
              </DiffAccordion>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Close
          </button>
          <button
            type="button"
            onClick={handleCompare}
            disabled={loading || !ontologyBKey}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            data-testid="schema-diff-compare-btn"
          >
            {loading ? "Comparing…" : "Compare"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="block text-xs font-medium text-gray-600 mb-1">{label}</div>
      {children}
    </div>
  );
}

function DiffAccordion({
  title,
  counts,
  open,
  onToggle,
  testId,
  children,
}: {
  title: string;
  counts: [number, number, number];
  open: boolean;
  onToggle: () => void;
  testId: string;
  children: React.ReactNode;
}) {
  const [added, removed, changed] = counts;
  const total = added + removed + changed;
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden" data-testid={testId}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
      >
        <span className="text-sm font-medium text-gray-900">{title}</span>
        <span className="text-xs text-gray-500">
          +{added} / −{removed} / Δ{changed}
          {total === 0 ? " (none)" : ""}
        </span>
      </button>
      {open && <div className="px-3 py-2 text-sm">{children}</div>}
    </div>
  );
}

function EntityBucket({
  added,
  removed,
  changed,
}: {
  added: SchemaDiffEntityRow[];
  removed: SchemaDiffEntityRow[];
  changed: SchemaDiffChangedEntityRow[];
}) {
  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return <p className="text-gray-500 text-xs">No differences in this bucket.</p>;
  }
  return (
    <div className="space-y-3">
      {added.length > 0 && (
        <BucketList title="Added" tone="green" items={added.map((r) => entityDiffLabel(r))} />
      )}
      {removed.length > 0 && (
        <BucketList title="Removed" tone="red" items={removed.map((r) => entityDiffLabel(r))} />
      )}
      {changed.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-amber-800 mb-1">Changed</div>
          <ul className="space-y-1">
            {changed.map((row) => (
              <li key={row.uri} className="text-xs text-gray-800">
                <span className="font-medium">{entityDiffLabel(row.after)}</span>
                <span className="text-gray-500 font-mono ml-1">({row.uri})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ConstraintBucket({
  added,
  removed,
  changed,
}: {
  added: Record<string, unknown>[];
  removed: Record<string, unknown>[];
  changed: SchemaDiffChangedConstraintRow[];
}) {
  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return <p className="text-gray-500 text-xs">No differences in this bucket.</p>;
  }
  const labelConstraint = (row: Record<string, unknown>) => {
    const cls = String(row.class_uri ?? "");
    const prop = String(row.property_uri ?? "");
    const rtype = String(row.restriction_type ?? "");
    if (cls && prop && rtype) {
      return constraintDiffLabel({
        class_uri: cls,
        property_uri: prop,
        restriction_type: rtype,
        before: {},
        after: {},
      });
    }
    return "(constraint)";
  };
  return (
    <div className="space-y-3">
      {added.length > 0 && (
        <BucketList title="Added" tone="green" items={added.map(labelConstraint)} />
      )}
      {removed.length > 0 && (
        <BucketList title="Removed" tone="red" items={removed.map(labelConstraint)} />
      )}
      {changed.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-amber-800 mb-1">Changed</div>
          <ul className="space-y-1">
            {changed.map((row) => (
              <li key={`${row.class_uri}:${row.property_uri}:${row.restriction_type}`} className="text-xs">
                {constraintDiffLabel(row)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function BucketList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "green" | "red";
  items: string[];
}) {
  const toneClass = tone === "green" ? "text-emerald-800" : "text-red-800";
  return (
    <div>
      <div className={`text-xs font-semibold mb-1 ${toneClass}`}>{title}</div>
      <ul className="list-disc list-inside text-xs text-gray-800 space-y-0.5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
