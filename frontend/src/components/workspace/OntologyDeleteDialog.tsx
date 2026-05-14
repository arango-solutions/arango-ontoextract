"use client";

/**
 * H.4 — Ontology delete dialog with cascade-on-delete dependency analysis.
 *
 * Replaces the previous typed-name ``ConfirmDialog`` flow for ontology
 * deletion. The old flow only showed a generic warning; this dialog
 * fetches ``GET /library/{id}/deletion-impact`` first so the user sees:
 *
 *   * Direct + transitive ontologies that import this one (with depth)
 *   * Cross-ontology ``extends_domain`` edge counts
 *   * Per-collection counts of entities/edges that will be soft-expired
 *   * Affected extraction runs, quality history snapshots, and released
 *     versions
 *
 * The destructive action is still gated by the typed-name confirmation
 * mandated by ``ui-architecture.mdc`` §18 ("irreversible destructive
 * → dedicated confirmation overlay"). The dialog cannot be confirmed
 * until the impact has loaded successfully (so the user is never asked
 * to confirm a delete whose blast radius is unknown).
 *
 * Visual / a11y conventions match ``ConfirmDialog``:
 *   * ``role="dialog"`` with ``aria-labelledby`` + ``aria-describedby``
 *   * Closes on backdrop click, Escape, and × button
 *   * Initial focus on the typed-name input once the impact loads
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/lib/api-client";
import {
  fetchOntologyDeletionImpact,
  type OntologyDeletionImpact,
} from "@/lib/ontologyDeletionImpact";

export interface OntologyDeleteDialogProps {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
  /** Fired only after the user typed the ontology name AND clicked
   *  "Delete". Receives the same ontology key so the parent can run its
   *  existing ``deleteOntology`` callback unchanged. */
  onConfirm: (ontologyId: string) => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; impact: OntologyDeletionImpact }
  | { kind: "error"; message: string };

export default function OntologyDeleteDialog({
  ontologyId,
  ontologyName,
  onClose,
  onConfirm,
}: OntologyDeleteDialogProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Fetch the impact analysis the moment the dialog mounts. AbortController
  // ensures a fast close-and-reopen on a different ontology doesn't race
  // an in-flight request from clobbering the new one.
  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    setTyped("");
    fetchOntologyDeletionImpact(ontologyId)
      .then((impact) => {
        if (cancelled) return;
        setState({ kind: "ready", impact });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError
            ? err.body?.message ?? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load deletion impact";
        setState({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  // Move focus into the typed-name input once the impact has loaded so
  // keyboard users can confirm without a tab jump. Re-running on state
  // change keeps the focus correct after a retry.
  useEffect(() => {
    if (state.kind === "ready") {
      inputRef.current?.focus();
    }
  }, [state.kind]);

  // Document-level Escape handler: works regardless of focus position.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const typedMatches = typed === ontologyName;
  const canConfirm = state.kind === "ready" && typedMatches;

  const titleId = "ontology-delete-dialog-title";
  const descriptionId = "ontology-delete-dialog-description";

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/50"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-gray-900">
              Delete ontology
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              <span className="font-medium text-gray-700">{ontologyName}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-600 -mt-1 -mr-2 px-2 py-1 text-lg leading-none"
          >
            ×
          </button>
        </div>

        <p id={descriptionId} className="text-sm text-gray-700 mb-4">
          This action cascades into classes, properties, edges, extraction runs,
          and quality history. It cannot be undone. Review the impact below.
        </p>

        {state.kind === "loading" && <ImpactLoading />}
        {state.kind === "error" && (
          <ImpactError message={state.message} ontologyId={ontologyId} />
        )}
        {state.kind === "ready" && <ImpactSummary impact={state.impact} />}

        <div className="mt-5 border-t border-gray-100 pt-4">
          <label
            htmlFor="ontology-delete-typed-name"
            className="block text-xs font-medium text-gray-600 mb-1"
          >
            Type the ontology name to confirm:
          </label>
          <input
            ref={inputRef}
            id="ontology-delete-typed-name"
            type="text"
            value={typed}
            disabled={state.kind !== "ready"}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={ontologyName}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono disabled:bg-gray-50 disabled:text-gray-400"
            onKeyDown={(e) => {
              if (e.key === "Enter" && canConfirm) {
                e.preventDefault();
                onConfirm(ontologyId);
              }
            }}
          />
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(ontologyId)}
            disabled={!canConfirm}
            className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// --- Subcomponents --------------------------------------------------------

function ImpactLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 py-8 text-sm text-gray-500"
    >
      <span className="h-5 w-5 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin" />
      Loading deletion impact…
    </div>
  );
}

function ImpactError({
  message,
  ontologyId,
}: {
  message: string;
  ontologyId: string;
}) {
  return (
    <div
      role="alert"
      className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700"
    >
      <p className="font-medium">Could not load deletion impact for {ontologyId}.</p>
      <p className="mt-1 text-red-600/90">{message}</p>
      <p className="mt-2 text-xs text-red-600/80">
        Confirmation is disabled until the impact loads. Close this dialog and
        try again, or contact an administrator if the problem persists.
      </p>
    </div>
  );
}

function ImpactSummary({ impact }: { impact: OntologyDeletionImpact }) {
  const expireRows = useMemo(
    () =>
      Object.entries(impact.expire_counts)
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]),
    [impact.expire_counts],
  );

  return (
    <div className="space-y-4">
      {impact.warnings.length > 0 && (
        <ul className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-800 space-y-1">
          {impact.warnings.map((w, idx) => (
            <li key={idx} className="flex gap-2">
              <span aria-hidden>!</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      {impact.transitive_dependents.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">
            Dependent ontologies ({impact.transitive_dependents.length})
          </h3>
          <p className="text-xs text-gray-500 mb-2">
            These ontologies import this one directly or transitively. After
            deletion their import edges will be expired.
          </p>
          <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-40 overflow-y-auto text-sm">
            {impact.transitive_dependents.map((d) => (
              <li
                key={d._key}
                className="flex items-center justify-between px-3 py-1.5"
              >
                <span className="truncate text-gray-800">{d.name}</span>
                <span className="ml-2 flex-shrink-0 text-xs text-gray-500">
                  depth {d.depth}
                  {d.status ? ` · ${d.status}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="text-sm font-semibold text-gray-700 mb-1">
          What will be expired
        </h3>
        {expireRows.length === 0 &&
        impact.cross_ontology_extends_edges === 0 &&
        impact.extraction_runs.total === 0 &&
        impact.quality_history_snapshots === 0 &&
        impact.released_versions === 0 ? (
          <p className="text-xs text-gray-500">
            No live entities, edges, runs, or history reference this ontology.
          </p>
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600">
            {expireRows.map(([col, count]) => (
              <div key={col} className="flex justify-between gap-2">
                <dt className="truncate">{col}</dt>
                <dd className="font-mono text-gray-800">{count}</dd>
              </div>
            ))}
            {impact.cross_ontology_extends_edges > 0 && (
              <div className="flex justify-between gap-2">
                <dt className="truncate">cross-ontology extends_domain</dt>
                <dd className="font-mono text-gray-800">
                  {impact.cross_ontology_extends_edges}
                </dd>
              </div>
            )}
            {impact.extraction_runs.total > 0 && (
              <div className="flex justify-between gap-2">
                <dt className="truncate">extraction runs (target/domain)</dt>
                <dd className="font-mono text-gray-800">
                  {impact.extraction_runs.as_target}/{impact.extraction_runs.as_domain}
                </dd>
              </div>
            )}
            {impact.quality_history_snapshots > 0 && (
              <div className="flex justify-between gap-2">
                <dt className="truncate">quality history snapshots</dt>
                <dd className="font-mono text-gray-800">
                  {impact.quality_history_snapshots}
                </dd>
              </div>
            )}
            {impact.released_versions > 0 && (
              <div className="flex justify-between gap-2">
                <dt className="truncate">released versions</dt>
                <dd className="font-mono text-gray-800">
                  {impact.released_versions}
                </dd>
              </div>
            )}
            {impact.open_revisions > 0 && (
              <div className="flex justify-between gap-2">
                <dt className="truncate">pending revisions</dt>
                <dd className="font-mono text-gray-800">{impact.open_revisions}</dd>
              </div>
            )}
          </dl>
        )}
      </section>

      {impact.imports_outgoing.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">
            This ontology imports ({impact.imports_outgoing.length})
          </h3>
          <p className="text-xs text-gray-500 mb-2">
            These imports are informational — the imported ontologies are not
            affected by deleting this one.
          </p>
          <ul className="text-xs text-gray-700 space-y-0.5 max-h-24 overflow-y-auto">
            {impact.imports_outgoing.map((o) => (
              <li key={o._key} className="truncate">
                {o.name}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
