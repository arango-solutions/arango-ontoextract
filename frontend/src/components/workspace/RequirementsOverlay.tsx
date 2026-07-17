"use client";

/**
 * Requirements & Coverage overlay (Stream 22 CQ-PR2 authoring + CQ-PR6 coverage,
 * PRD §6.19).
 *
 * Author the ontology's use cases + competency questions (human-authored — the
 * spec's whole point), save them, and run a coverage check to see which CQs the
 * ontology can answer and where the gaps are.
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); Esc closes.
 *
 * Backend (see app/api/ontology/requirements.py + app/services/cq_coverage.py):
 *   GET    /api/v1/ontology/{id}/requirements
 *   PUT    /api/v1/ontology/{id}/requirements
 *   POST   /api/v1/ontology/{id}/coverage
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface CompetencyQuestion {
  text: string;
  priority: string;
  status?: string;
  query?: string | null;
}

interface UseCase {
  name: string;
  priority: string;
  competency_questions: CompetencyQuestion[];
}

interface Spec {
  purpose: string;
  use_cases: UseCase[];
}

interface CoverageReport {
  total: number;
  answerable: number;
  unanswerable: number;
  unformalized: number;
  error: number;
  coverage_pct: number;
  by_use_case: Record<string, { total: number; answerable: number }>;
  gaps: Array<{ text: string; use_case: string | null; status: string }>;
}

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
}

const PRIORITIES = ["low", "medium", "high"];

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

const EMPTY_SPEC: Spec = { purpose: "", use_cases: [] };

export default function RequirementsOverlay({ ontologyId, ontologyName, onClose }: Props) {
  const [spec, setSpec] = useState<Spec>(EMPTY_SPEC);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);

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
      try {
        const res = await api.get<Partial<Spec>>(
          `/api/v1/ontology/${encodeURIComponent(ontologyId)}/requirements`,
        );
        if (cancelled) return;
        setSpec({ purpose: res.purpose ?? "", use_cases: res.use_cases ?? [] });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setSpec(EMPTY_SPEC); // no spec yet — start fresh
        } else {
          setError(errMsg(err, "Failed to load requirements"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  // ---- immutable editors ----
  const addUseCase = () =>
    setSpec((s) => ({
      ...s,
      use_cases: [...s.use_cases, { name: "", priority: "medium", competency_questions: [] }],
    }));

  const removeUseCase = (i: number) =>
    setSpec((s) => ({ ...s, use_cases: s.use_cases.filter((_, idx) => idx !== i) }));

  const editUseCase = (i: number, patch: Partial<UseCase>) =>
    setSpec((s) => ({
      ...s,
      use_cases: s.use_cases.map((uc, idx) => (idx === i ? { ...uc, ...patch } : uc)),
    }));

  const addCq = (i: number) =>
    editUseCase(i, {
      competency_questions: [
        ...spec.use_cases[i].competency_questions,
        { text: "", priority: "medium" },
      ],
    });

  const editCq = (i: number, j: number, patch: Partial<CompetencyQuestion>) =>
    editUseCase(i, {
      competency_questions: spec.use_cases[i].competency_questions.map((cq, idx) =>
        idx === j ? { ...cq, ...patch } : cq,
      ),
    });

  const removeCq = (i: number, j: number) =>
    editUseCase(i, {
      competency_questions: spec.use_cases[i].competency_questions.filter((_, idx) => idx !== j),
    });

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await api.put(`/api/v1/ontology/${encodeURIComponent(ontologyId)}/requirements`, spec);
      setToast("Saved");
    } catch (err) {
      setError(errMsg(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  }, [ontologyId, spec]);

  const runCoverage = useCallback(async () => {
    setCoverageLoading(true);
    setError(null);
    try {
      const res = await api.post<CoverageReport>(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/coverage`,
      );
      setCoverage(res);
    } catch (err) {
      setError(errMsg(err, "Coverage check failed"));
    } finally {
      setCoverageLoading(false);
    }
  }, [ontologyId]);

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[620px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Requirements and coverage"
      data-testid="requirements-overlay"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">
          Requirements &amp; coverage · {ontologyName}
        </h2>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-400 hover:text-slate-700"
          data-testid="requirements-close"
        >
          ✕
        </button>
      </div>

      {error && (
        <div className="px-5 py-2 text-sm text-rose-700 bg-rose-50" data-testid="requirements-error">
          {error}
        </div>
      )}
      {toast && (
        <div
          className="px-5 py-2 text-sm text-slate-600 bg-slate-50"
          data-testid="requirements-toast"
        >
          {toast}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div data-testid="requirements-loading" className="text-sm text-slate-400">
            Loading…
          </div>
        ) : (
          <div data-testid="requirements-editor">
            <label className="block text-xs font-medium text-slate-500 mb-1">Purpose</label>
            <textarea
              value={spec.purpose}
              onChange={(e) => setSpec((s) => ({ ...s, purpose: e.target.value }))}
              className="w-full text-sm border border-slate-200 rounded p-2 mb-4"
              rows={2}
              data-testid="requirements-purpose"
            />

            {spec.use_cases.map((uc, i) => (
              <div
                key={i}
                className="border border-slate-200 rounded-lg p-3 mb-3"
                data-testid={`use-case-${i}`}
              >
                <div className="flex gap-2 items-center mb-2">
                  <input
                    value={uc.name}
                    onChange={(e) => editUseCase(i, { name: e.target.value })}
                    placeholder="Use case name"
                    className="flex-1 text-sm font-medium border border-slate-200 rounded px-2 py-1"
                    data-testid={`use-case-name-${i}`}
                  />
                  <select
                    value={uc.priority}
                    onChange={(e) => editUseCase(i, { priority: e.target.value })}
                    className="text-xs border border-slate-200 rounded px-1 py-1"
                    data-testid={`use-case-priority-${i}`}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => removeUseCase(i)}
                    className="text-xs text-rose-600"
                    data-testid={`use-case-remove-${i}`}
                  >
                    Remove
                  </button>
                </div>
                {uc.competency_questions.map((cq, j) => (
                  <div key={j} className="flex gap-2 items-center mb-1" data-testid={`cq-${i}-${j}`}>
                    <input
                      value={cq.text}
                      onChange={(e) => editCq(i, j, { text: e.target.value })}
                      placeholder="Competency question"
                      className="flex-1 text-sm border border-slate-200 rounded px-2 py-1"
                      data-testid={`cq-text-${i}-${j}`}
                    />
                    <button
                      onClick={() => removeCq(i, j)}
                      className="text-xs text-rose-500"
                      data-testid={`cq-remove-${i}-${j}`}
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button
                  onClick={() => addCq(i)}
                  className="text-xs text-emerald-700 mt-1"
                  data-testid={`cq-add-${i}`}
                >
                  + Add question
                </button>
              </div>
            ))}

            <button
              onClick={addUseCase}
              className="text-sm text-emerald-700 mb-4"
              data-testid="use-case-add"
            >
              + Add use case
            </button>

            <div className="flex gap-2 border-t border-slate-100 pt-3">
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg disabled:opacity-40"
                data-testid="requirements-save"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                onClick={runCoverage}
                disabled={coverageLoading}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg disabled:opacity-40"
                data-testid="requirements-run-coverage"
              >
                {coverageLoading ? "Checking…" : "Run coverage"}
              </button>
            </div>

            {coverage && (
              <div className="mt-4 border-t border-slate-100 pt-3" data-testid="coverage-report">
                <div className="text-sm font-semibold text-slate-800 mb-1">
                  Coverage: {coverage.coverage_pct}% ({coverage.answerable}/{coverage.total})
                </div>
                <div className="text-xs text-slate-500 mb-2">
                  answerable {coverage.answerable} · unanswerable {coverage.unanswerable} ·
                  unformalized {coverage.unformalized} · error {coverage.error}
                </div>
                {coverage.gaps.length > 0 && (
                  <ul className="text-xs text-slate-600 space-y-0.5" data-testid="coverage-gaps">
                    {coverage.gaps.map((g, k) => (
                      <li key={k}>
                        <span className="text-rose-600">{g.status}</span> — {g.text}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
