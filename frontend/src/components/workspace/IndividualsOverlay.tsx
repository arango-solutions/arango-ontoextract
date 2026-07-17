"use client";

/**
 * A-box instance lens (Stream 21 AB-PR6, PRD §6.18 FR-18.9).
 *
 * Lists the named individuals (instances) extracted for the open ontology, each
 * with its rdf:type class and how many source spans it was grounded in. Read-only
 * for now; accept/reject/edit curation is a follow-up.
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); Esc closes.
 *
 * Backend: GET /api/v1/ontology/{id}/individuals
 */

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface IndividualRow {
  _key: string;
  label: string;
  type_label?: string | null;
  type_key?: string | null;
  provenance?: Array<Record<string, unknown>> | null;
}

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
}

export default function IndividualsOverlay({ ontologyId, ontologyName, onClose }: Props) {
  const [rows, setRows] = useState<IndividualRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await api.get<{ data?: IndividualRow[] }>(
          `/api/v1/ontology/${encodeURIComponent(ontologyId)}/individuals?limit=500`,
        );
        if (!cancelled) setRows(res.data ?? []);
      } catch (err) {
        if (!cancelled) {
          const msg =
            err instanceof ApiError
              ? err.body.message
              : err instanceof Error
                ? err.message
                : "Failed to load individuals";
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[560px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Instances"
      data-testid="individuals-overlay"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">
          Instances (A-box) · {ontologyName}
        </h2>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-400 hover:text-slate-700"
          data-testid="individuals-close"
        >
          ✕
        </button>
      </div>

      {error && (
        <div className="px-5 py-2 text-sm text-rose-700 bg-rose-50" data-testid="individuals-error">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div className="text-sm text-slate-400" data-testid="individuals-loading">
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-slate-400" data-testid="individuals-empty">
            No individuals extracted for this ontology yet.
          </div>
        ) : (
          <ul className="space-y-1" data-testid="individuals-list">
            {rows.map((r) => {
              const spans = Array.isArray(r.provenance) ? r.provenance.length : 0;
              return (
                <li
                  key={r._key}
                  className="flex items-center justify-between border border-slate-100 rounded px-3 py-2 text-sm"
                  data-testid={`individual-${r._key}`}
                >
                  <span className="font-medium text-slate-800">{r.label}</span>
                  <span className="flex items-center gap-2 text-xs text-slate-500">
                    {r.type_label && (
                      <span className="px-2 py-0.5 rounded-full bg-slate-100" data-testid={`individual-type-${r._key}`}>
                        {r.type_label}
                      </span>
                    )}
                    <span title="source spans">📎 {spans}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
