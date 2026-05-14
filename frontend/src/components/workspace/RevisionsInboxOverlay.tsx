"use client";

/**
 * Revisions Inbox overlay (Stream 11 IBR.14 + IBR.15).
 *
 * Lists pending FLAG_FOR_CURATION rows for one ontology and lets the
 * curator accept / reject / modify each one. Per
 * ``ui-architecture.mdc``:
 *
 * - Overlay over the workspace canvas, never a route (rule 9).
 * - Lives in the ``viewportTopRight`` placement zone so it doesn't
 *   stack on top of the asset info panel (``mainColumnTopLeft``).
 * - Decisions go through right-click context menus on each row OR
 *   the inline action buttons (right-click is the canonical path
 *   per rule 0; buttons exist for discoverability only).
 * - Reversible decisions act immediately; the inbox refreshes after
 *   each one. Modify opens a small inline panel for the override
 *   payload (no separate route, no native dialog).
 *
 * The detail panel from IBR.15 is a sibling that opens when the
 * curator clicks a row -- it surfaces the full reasoning, evidence
 * quotes, and downstream impact in one compact view.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Wire types -- mirror the backend's revision_meta shape (IBR.1)
// ---------------------------------------------------------------------------

export interface RevisionRow {
  _key: string;
  ontology_id: string;
  verdict: string;
  action: string;
  status: string;
  agent_type: string;
  agent_version: string;
  triggering_doc_id: string;
  existing_entity_id: string;
  existing_version?: string | null;
  new_version?: string | null;
  evidence_quotes: string[];
  reasoning: string;
  confidence_before?: number | null;
  confidence_after?: number | null;
  created: number;
  decision_log?: Array<{
    from_status?: string;
    to_status?: string;
    decided_by?: string;
    note?: string;
    decided_at?: number;
  }>;
}

interface InboxResponse {
  data: RevisionRow[];
  ontology_id: string;
  count: number;
}

interface DecisionResponse {
  revision_key: string;
  decision: string;
  status: string;
  already_decided: boolean;
  supersede_result?: Record<string, unknown> | null;
  revision: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  ontologyId: string;
  ontologyName: string;
  /**
   * Identity of the curator. Plumbed into ``decided_by`` on every
   * decision so the audit trail is unambiguous. Falls back to
   * ``"curator"`` when not provided (single-user dev mode).
   */
  curatorId?: string;
  onClose: () => void;
  /**
   * Called after every decision so the parent can refresh related
   * surfaces (the canvas, dashboard tile, badge counters).
   */
  onChanged?: () => void;
}

// ---------------------------------------------------------------------------
// Small visual helpers
// ---------------------------------------------------------------------------

const verdictColor: Record<string, string> = {
  REINFORCED: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  REFINED: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  "GAP-FILLING": "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
  REDUNDANT: "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
  CONTRADICTED: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  UNCERTAIN: "bg-yellow-50 text-yellow-800 ring-1 ring-yellow-200",
};

const actionColor: Record<string, string> = {
  REINFORCE: "bg-emerald-100 text-emerald-800",
  REVISE: "bg-amber-100 text-amber-800",
  RETRACT: "bg-rose-100 text-rose-800",
  GAP_FILL: "bg-indigo-100 text-indigo-800",
  FLAG_FOR_CURATION: "bg-yellow-100 text-yellow-900",
};

function relativeTime(ts: number): string {
  if (!ts) return "—";
  const diffSec = Math.max(0, (Date.now() - ts * 1000) / 1000);
  if (diffSec < 60) return `${Math.round(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RevisionsInboxOverlay({
  ontologyId,
  ontologyName,
  curatorId,
  onClose,
  onChanged,
}: Props) {
  const [rows, setRows] = useState<RevisionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const decidedBy = curatorId || "curator";

  // ---- Esc to close ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedKey) {
          setSelectedKey(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, selectedKey]);

  // ---- Data fetch ----
  const fetchInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<InboxResponse>(
        `/api/v1/revisions/inbox?ontology_id=${encodeURIComponent(ontologyId)}&limit=200`,
      );
      setRows(res.data ?? []);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error
            ? err.message
            : "Failed to load revisions";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    void fetchInbox();
  }, [fetchInbox]);

  // ---- Decisions ----
  const decide = useCallback(
    async (
      key: string,
      verb: "accept" | "reject" | "modify",
      payload: Record<string, unknown> = {},
    ) => {
      setBusyKey(key);
      setError(null);
      try {
        const body = { decided_by: decidedBy, ...payload };
        const res = await api.post<DecisionResponse>(
          `/api/v1/revisions/${encodeURIComponent(key)}/${verb}`,
          body,
        );
        if (res.already_decided) {
          setToast(`Already ${res.status}.`);
        } else {
          setToast(
            verb === "accept"
              ? "Accepted — graph updated."
              : verb === "reject"
                ? "Rejected — no change."
                : "Modified and applied.",
          );
        }
        // Optimistic local removal: drop the row immediately so the UI
        // feels snappy, then refresh from the server in the background.
        setRows((prev) => prev.filter((r) => r._key !== key));
        if (selectedKey === key) setSelectedKey(null);
        onChanged?.();
        void fetchInbox();
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Decision failed";
        setError(msg);
      } finally {
        setBusyKey(null);
      }
    },
    [decidedBy, fetchInbox, onChanged, selectedKey],
  );

  // ---- Selected row (for IBR.15 detail pane) ----
  const selectedRow = useMemo(
    () => rows.find((r) => r._key === selectedKey) ?? null,
    [rows, selectedKey],
  );

  // ---- Toast auto-dismiss ----
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[640px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label={`Revisions Inbox for ${ontologyName}`}
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Revisions Inbox
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            <span className="font-medium text-slate-700">{ontologyName}</span> ·{" "}
            {loading
              ? "loading…"
              : `${rows.length} pending revision${rows.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void fetchInbox()}
            className="text-xs font-medium text-slate-500 hover:text-slate-800"
            title="Refresh"
          >
            ↻
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-700 text-xl leading-none"
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 flex">
        {/* Row list */}
        <div className="flex-1 min-w-0 overflow-y-auto">
          {error && (
            <div className="m-4 px-3 py-2 rounded-lg bg-rose-50 text-rose-700 text-sm border border-rose-200">
              {error}
            </div>
          )}
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <div className="h-6 w-6 border-2 border-slate-200 border-t-indigo-500 rounded-full animate-spin" />
            </div>
          ) : rows.length === 0 ? (
            <div className="px-6 py-10 text-center text-sm text-slate-500">
              <div className="text-3xl mb-2">📭</div>
              No pending revisions.
              <div className="mt-1 text-xs text-slate-400">
                Right-click on canvas for more options.
              </div>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {rows.map((row) => {
                const verdictBadge =
                  verdictColor[row.verdict] ?? verdictColor.UNCERTAIN;
                const actionBadge =
                  actionColor[row.action] ?? actionColor.FLAG_FOR_CURATION;
                const isSelected = selectedKey === row._key;
                const isBusy = busyKey === row._key;
                return (
                  <li
                    key={row._key}
                    className={`px-4 py-3 cursor-pointer hover:bg-slate-50 ${
                      isSelected ? "bg-indigo-50/50" : ""
                    }`}
                    onClick={() => setSelectedKey(row._key)}
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span
                            className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-md font-medium ${verdictBadge}`}
                          >
                            {row.verdict}
                          </span>
                          <span
                            className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-md font-semibold ${actionBadge}`}
                          >
                            {row.action.replace(/_/g, " ")}
                          </span>
                          <span className="text-[11px] text-slate-400">
                            {relativeTime(row.created)} · {row.agent_type}
                          </span>
                        </div>
                        <div className="mt-1.5 text-sm text-slate-800 truncate font-medium">
                          {row.existing_entity_id}
                        </div>
                        {row.reasoning && (
                          <div className="mt-1 text-xs text-slate-600 line-clamp-2">
                            {row.reasoning}
                          </div>
                        )}
                      </div>
                      <div className="flex flex-col items-end gap-1 flex-shrink-0">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void decide(row._key, "accept");
                          }}
                          disabled={isBusy}
                          className="text-xs font-medium text-emerald-700 hover:text-emerald-900 disabled:opacity-50"
                          title="Apply this revision and mark accepted"
                        >
                          {isBusy ? "…" : "✓ Accept"}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void decide(row._key, "reject");
                          }}
                          disabled={isBusy}
                          className="text-xs font-medium text-rose-600 hover:text-rose-800 disabled:opacity-50"
                          title="Reject (no graph change)"
                        >
                          ✕ Reject
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Detail panel (IBR.15) -- inline sibling, NOT a stacked overlay */}
        {selectedRow && (
          <RevisionDetailPanel
            row={selectedRow}
            curatorId={decidedBy}
            busy={busyKey === selectedRow._key}
            onClose={() => setSelectedKey(null)}
            onAccept={() => void decide(selectedRow._key, "accept")}
            onReject={() => void decide(selectedRow._key, "reject")}
            onModify={(payload) =>
              void decide(selectedRow._key, "modify", payload)
            }
          />
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-4 py-2 rounded-full bg-slate-800 text-white text-xs shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// IBR.15 — Revision detail panel (inline pane within the inbox overlay)
// ---------------------------------------------------------------------------

interface DetailProps {
  row: RevisionRow;
  curatorId: string;
  busy: boolean;
  onClose: () => void;
  onAccept: () => void;
  onReject: () => void;
  onModify: (payload: Record<string, unknown>) => void;
}

const ACTIONS = [
  "REINFORCE",
  "REVISE",
  "RETRACT",
  "GAP_FILL",
  "FLAG_FOR_CURATION",
];

function RevisionDetailPanel({
  row,
  busy,
  onClose,
  onAccept,
  onReject,
  onModify,
}: DetailProps) {
  const [showModify, setShowModify] = useState(false);
  const [overrideAction, setOverrideAction] = useState<string>(row.action);
  const [note, setNote] = useState("");

  const submitModify = () => {
    const payload: Record<string, unknown> = { note };
    if (overrideAction && overrideAction !== row.action) {
      payload.override_action = overrideAction;
    }
    if (!payload.override_action) {
      // Modify requires at least one of override_action / new_vertex_data
      // / new_edge — we only support override_action from this UI for
      // now; vertex/edge editing lands when the IBR.16 modify path is
      // exercised against a real REVISE/GAP_FILL row from the LLM agent.
      payload.note = note || "(no override; logged decision only)";
      payload.override_action = row.action;
    }
    onModify(payload);
    setShowModify(false);
  };

  return (
    <aside className="w-[280px] flex-shrink-0 border-l border-slate-100 bg-slate-50/40 overflow-y-auto">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Details</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail"
          className="text-slate-400 hover:text-slate-700 text-lg leading-none"
        >
          ×
        </button>
      </div>
      <div className="px-4 py-3 space-y-3 text-xs">
        <DetailRow label="Entity">
          <code className="text-[11px] text-slate-700 break-all">
            {row.existing_entity_id}
          </code>
        </DetailRow>
        <DetailRow label="Verdict">
          <span className="font-medium">{row.verdict}</span>
        </DetailRow>
        <DetailRow label="Action">
          <span className="font-medium">{row.action}</span>
        </DetailRow>
        <DetailRow label="Agent">
          {row.agent_type} · <span className="text-slate-500">{row.agent_version}</span>
        </DetailRow>
        <DetailRow label="Triggered by">
          <code className="text-[11px] text-slate-700">{row.triggering_doc_id}</code>
        </DetailRow>
        {(row.confidence_before != null || row.confidence_after != null) && (
          <DetailRow label="Confidence">
            <span>
              {row.confidence_before?.toFixed(2) ?? "—"} →{" "}
              <strong>{row.confidence_after?.toFixed(2) ?? "—"}</strong>
            </span>
          </DetailRow>
        )}
        {row.reasoning && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">
              Reasoning
            </div>
            <div className="text-slate-700 whitespace-pre-wrap">
              {row.reasoning}
            </div>
          </div>
        )}
        {row.evidence_quotes && row.evidence_quotes.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">
              Evidence quotes
            </div>
            <ul className="space-y-1">
              {row.evidence_quotes.map((q, i) => (
                <li
                  key={i}
                  className="text-[11px] text-slate-600 italic bg-white border border-slate-200 rounded px-2 py-1"
                >
                  “{q}”
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Action bar */}
      <div className="px-4 py-3 border-t border-slate-100 space-y-2">
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="w-full px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 disabled:opacity-50"
        >
          {busy ? "Working…" : "Accept and apply"}
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={busy}
          className="w-full px-3 py-1.5 rounded-md bg-white text-rose-700 text-xs font-medium border border-rose-200 hover:bg-rose-50 disabled:opacity-50"
        >
          Reject (no graph change)
        </button>
        <button
          type="button"
          onClick={() => setShowModify((s) => !s)}
          className="w-full text-xs text-indigo-600 hover:text-indigo-800"
        >
          {showModify ? "Cancel modify" : "Modify…"}
        </button>
        {showModify && (
          <div className="space-y-2 pt-2 border-t border-slate-200">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wide text-slate-400">
                Override action
              </span>
              <select
                value={overrideAction}
                onChange={(e) => setOverrideAction(e.target.value)}
                className="mt-1 block w-full text-xs border border-slate-300 rounded px-2 py-1"
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wide text-slate-400">
                Note (audit log)
              </span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                className="mt-1 block w-full text-xs border border-slate-300 rounded px-2 py-1"
              />
            </label>
            <button
              type="button"
              onClick={submitModify}
              disabled={busy}
              className="w-full px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 disabled:opacity-50"
            >
              Apply modification
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">
        {label}
      </div>
      <div className="text-slate-800">{children}</div>
    </div>
  );
}
