"use client";

/**
 * EdgeRepairOverlay
 *
 * Preview-and-apply UI surface for the orphan-object-property repair
 * workflow. Mirrors :func:`backend.app.services.edge_repair.repair_orphan_object_property_ranges`:
 *
 * 1. On open, fires a ``dry_run=true`` POST to fetch the would-be
 *    repairs and renders them in a table (prop / domain -> range,
 *    matched-via, matched-text snippet).
 * 2. The "Apply" button fires the same endpoint without ``dry_run`` --
 *    the server inserts the ``rdfs_range_class`` edges with a
 *    ``repair_meta`` audit field. Idempotent: re-running finds zero.
 * 3. On success, switches to a confirmation panel with counts and
 *    invokes ``onChanged()`` so the parent can refresh the canvas.
 *
 * Per ``ui-architecture.mdc`` rule 18, this is a *constructive*
 * destructive action -- we don't gate it behind a typed-name confirm,
 * but we do show the full preview before any write so users can spot
 * a bad inferred match before it lands.
 *
 * Per rule 9 this is an overlay over the workspace canvas, opened from
 * the ontology context menu, never a route.
 *
 * The ``unrecoverable`` and ``no_domain`` buckets are shown as
 * read-only sections (they cannot be repaired by this endpoint --
 * they are honest signals that those concepts need new evidence or
 * human curation; emitted by the R3 rule via the reflection report).
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api-client";
import {
  applyEdgeRepair,
  previewEdgeRepair,
  type EdgeRepairReport,
} from "@/lib/edgeRepair";

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
  /** Fired after a successful Apply so the parent can refresh the
   *  workspace canvas (the 20 newly-visible class-to-class edges only
   *  appear after a re-fetch). */
  onApplied: () => void;
}

type Phase = "loading" | "preview" | "applying" | "applied" | "error";

export default function EdgeRepairOverlay({
  ontologyId,
  ontologyName,
  onClose,
  onApplied,
}: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [report, setReport] = useState<EdgeRepairReport | null>(null);
  const [appliedReport, setAppliedReport] = useState<EdgeRepairReport | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  const loadPreview = useCallback(async () => {
    setPhase("loading");
    setError(null);
    try {
      const r = await previewEdgeRepair(ontologyId);
      setReport(r);
      setPhase("preview");
    } catch (err) {
      setError(formatErr(err, "Failed to load repair preview"));
      setPhase("error");
    }
  }, [ontologyId]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  const handleApply = useCallback(async () => {
    setPhase("applying");
    setError(null);
    try {
      const r = await applyEdgeRepair(ontologyId);
      setAppliedReport(r);
      setPhase("applied");
      onApplied();
    } catch (err) {
      setError(formatErr(err, "Failed to apply repairs"));
      setPhase("error");
    }
  }, [ontologyId, onApplied]);

  const repaired = report?.repaired ?? [];
  const unrecoverable = report?.unrecoverable ?? [];
  const noDomain = report?.no_domain ?? [];

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edge-repair-overlay-title"
    >
      <div className="relative bg-white rounded-2xl shadow-2xl w-[90vw] max-w-[1100px] max-h-[90vh] overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close"
        >
          ×
        </button>

        <div className="p-8 pb-6 border-b border-gray-200">
          <h2
            id="edge-repair-overlay-title"
            className="text-xl font-semibold text-gray-800"
          >
            🔧 Repair Orphan Properties
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            {ontologyName}
          </p>
          <p className="mt-3 text-xs text-gray-500 leading-snug max-w-3xl">
            Object properties that have an <code>rdfs:domain</code> but no{" "}
            <code>rdfs:range</code> class are invisible on the canvas. The
            matcher infers a range from the property&apos;s own description
            and evidence text. Review the inferred matches below, then{" "}
            <span className="font-medium">Apply</span> to insert the missing
            edges (idempotent and audited via <code>repair_meta</code>).
          </p>
        </div>

        <div className="p-8 space-y-6">
          {phase === "loading" && (
            <p className="text-sm text-gray-500">Scanning for orphans…</p>
          )}

          {phase === "error" && error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <p className="font-medium">{error}</p>
              <button
                type="button"
                onClick={loadPreview}
                className="mt-2 text-xs underline hover:text-red-900"
              >
                Try again
              </button>
            </div>
          )}

          {phase === "applied" && appliedReport && (
            <AppliedSummary report={appliedReport} onClose={onClose} />
          )}

          {(phase === "preview" || phase === "applying") && report && (
            <>
              <SummaryBar report={report} />

              {repaired.length > 0 && (
                <RepairableSection rows={repaired} />
              )}

              {unrecoverable.length > 0 && (
                <UnrecoverableSection rows={unrecoverable} />
              )}

              {noDomain.length > 0 && (
                <NoDomainSection keys={noDomain} />
              )}

              {report.orphans_found === 0 && (
                <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
                  No orphan object properties found. This ontology&apos;s
                  range edges are all wired up.
                </div>
              )}

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                  disabled={phase === "applying"}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleApply}
                  disabled={phase === "applying" || repaired.length === 0}
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                >
                  {phase === "applying"
                    ? "Applying…"
                    : repaired.length === 0
                      ? "Nothing to apply"
                      : `Apply ${repaired.length} ${repaired.length === 1 ? "repair" : "repairs"}`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function formatErr(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message || fallback;
  if (err instanceof Error) return err.message;
  return fallback;
}

function SummaryBar({ report }: { report: EdgeRepairReport }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
      <Stat label="Orphans found" value={report.orphans_found} />
      <Stat
        label="Repairable"
        value={report.repaired_count}
        tone={report.repaired_count > 0 ? "good" : undefined}
      />
      <Stat
        label="Unrecoverable"
        value={report.unrecoverable_count}
        tone={report.unrecoverable_count > 0 ? "warn" : undefined}
      />
      <Stat
        label="No domain"
        value={report.no_domain_count}
        tone={report.no_domain_count > 0 ? "bad" : undefined}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "good" | "warn" | "bad";
}) {
  const toneClasses =
    tone === "good"
      ? "text-blue-700 bg-blue-50 border-blue-200"
      : tone === "warn"
        ? "text-amber-700 bg-amber-50 border-amber-200"
        : tone === "bad"
          ? "text-red-700 bg-red-50 border-red-200"
          : "text-gray-700 bg-gray-50 border-gray-200";
  return (
    <div className={`rounded-lg border px-4 py-3 ${toneClasses}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide opacity-75">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function RepairableSection({
  rows,
}: {
  rows: EdgeRepairReport["repaired"];
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-800 mb-2">
        Repairable ({rows.length})
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        The matcher inferred a range class from each property&apos;s own
        description / evidence. Apply will insert these as{" "}
        <code>rdfs_range_class</code> edges.
      </p>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">Property</th>
              <th className="px-3 py-2">Domain</th>
              <th className="px-3 py-2">→ Range</th>
              <th className="px-3 py-2">Matched via</th>
              <th className="px-3 py-2">Matched text</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((r) => (
              <tr key={r.prop_key} className="hover:bg-blue-50/50">
                <td className="px-3 py-2 font-mono text-xs text-gray-800">
                  {r.prop_key}
                </td>
                <td className="px-3 py-2 text-gray-700">
                  {r.domain_class_key}
                </td>
                <td className="px-3 py-2 font-medium text-blue-700">
                  {r.range_class_key}
                </td>
                <td className="px-3 py-2">
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-700">
                    {r.matched_via}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 max-w-md truncate">
                  {r.matched_text || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UnrecoverableSection({
  rows,
}: {
  rows: EdgeRepairReport["unrecoverable"];
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-800 mb-2">
        Unrecoverable ({rows.length})
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        No candidate range class matched these properties&apos;
        descriptions. They likely need new evidence (a class that
        doesn&apos;t yet exist) or human curation.
      </p>
      <ul className="space-y-1 text-sm">
        {rows.map((u) => (
          <li
            key={u.prop_key}
            className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2"
          >
            <p className="font-mono text-xs text-amber-900">{u.prop_key}</p>
            <p className="text-xs text-amber-800">
              <span className="font-medium">label:</span> {u.label || "—"}
              {u.domain_class_key && (
                <>
                  {" • "}
                  <span className="font-medium">domain:</span>{" "}
                  {u.domain_class_key}
                </>
              )}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NoDomainSection({ keys }: { keys: string[] }) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-800 mb-2">
        No domain ({keys.length})
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        These properties have neither <code>rdfs:domain</code> nor{" "}
        <code>rdfs:range</code> -- structurally broken; cannot appear on the
        canvas.
      </p>
      <ul className="space-y-1">
        {keys.map((k) => (
          <li
            key={k}
            className="rounded-md border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-900"
          >
            {k}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AppliedSummary({
  report,
  onClose,
}: {
  report: EdgeRepairReport;
  onClose: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-4">
        <p className="text-base font-semibold text-green-800">
          ✓ Repair complete
        </p>
        <p className="mt-1 text-sm text-green-700">
          Inserted{" "}
          <span className="font-bold">{report.repaired_count}</span>{" "}
          {report.repaired_count === 1 ? "edge" : "edges"} into the
          ontology. The canvas will refresh when you close this dialog.
        </p>
        {report.unrecoverable_count > 0 && (
          <p className="mt-2 text-xs text-green-700">
            {report.unrecoverable_count} property
            {report.unrecoverable_count === 1 ? "" : "s"} still need
            {report.unrecoverable_count === 1 ? "s" : ""} new evidence or
            human curation.
          </p>
        )}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
        >
          Close
        </button>
      </div>
    </div>
  );
}
