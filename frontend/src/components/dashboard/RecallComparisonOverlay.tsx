"use client";

/**
 * Q.4 — Gold-standard recall comparison overlay.
 *
 * Lets the operator drop an OWL/TTL reference document, choose a fuzzy
 * match threshold, and see precision / recall / F1 plus the full list
 * of matched / missed / false-positive concepts for one ontology.
 *
 * Per ``ui-architecture.mdc``:
 *  - This is an overlay opened from a context-menu / button on the
 *    Quality Report. It does NOT introduce a new route.
 *  - Esc closes the overlay; backdrop click closes the overlay.
 *  - File picker is the only input control; threshold + format default
 *    sensibly so a one-click happy path exists for "I just want to see
 *    recall".
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api-client";
import {
  computeQualityRecall,
  inferRdfFormatFromFilename,
  type RdfFormat,
  type RecallReport,
  type RecallSection,
} from "@/lib/qualityRecall";

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
}

const FORMAT_OPTIONS: { value: RdfFormat; label: string }[] = [
  { value: "turtle", label: "Turtle (.ttl)" },
  { value: "xml", label: "RDF/XML (.owl / .rdf)" },
  { value: "nt", label: "N-Triples (.nt)" },
  { value: "json-ld", label: "JSON-LD" },
];

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export default function RecallComparisonOverlay({
  ontologyId,
  ontologyName,
  onClose,
}: Props) {
  const [filename, setFilename] = useState<string>("");
  const [referenceContent, setReferenceContent] = useState<string>("");
  const [rdfFormat, setRdfFormat] = useState<RdfFormat>("turtle");
  const [threshold, setThreshold] = useState<number>(0.85);
  const [includeProps, setIncludeProps] = useState<boolean>(true);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<RecallReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function handleKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleFile = useCallback(async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    setRdfFormat(inferRdfFormatFromFilename(file.name));
    try {
      const text = await file.text();
      setReferenceContent(text);
      setError(null);
    } catch (err) {
      setError(`Could not read file: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, []);

  const runComparison = useCallback(async () => {
    if (!referenceContent) {
      setError("Choose a reference OWL/TTL file first.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const result = await computeQualityRecall({
        ontology_id: ontologyId,
        reference_content: referenceContent,
        rdf_format: rdfFormat,
        match_threshold: threshold,
        include_object_properties: includeProps,
      });
      setReport(result);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.body.message || `Recall computation failed (${err.status})`);
      } else {
        setError(err instanceof Error ? err.message : "Recall computation failed");
      }
      setReport(null);
    } finally {
      setRunning(false);
    }
  }, [ontologyId, referenceContent, rdfFormat, threshold, includeProps]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-6"
      onClick={onClose}
      data-testid="recall-overlay-backdrop"
    >
      <div
        className="w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Gold-standard recall comparison"
      >
        <header className="flex items-start justify-between gap-4 border-b border-gray-100 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
              Quality
            </p>
            <h2 className="mt-1 text-xl font-bold text-gray-900">
              Compare to gold-standard
            </h2>
            <p className="mt-0.5 text-sm text-gray-500">{ontologyName}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1 text-sm text-gray-500 hover:bg-gray-50"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <section className="space-y-4 px-6 py-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-gray-700">Reference file (OWL / TTL)</span>
              <input
                type="file"
                accept=".ttl,.owl,.rdf,.xml,.nt,.jsonld,.json-ld"
                onChange={handleFile}
                className="text-xs"
                data-testid="recall-file-input"
              />
              {filename && (
                <span className="text-xs text-gray-500" data-testid="recall-filename">
                  {filename}
                </span>
              )}
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-gray-700">Format</span>
              <select
                value={rdfFormat}
                onChange={(e) => setRdfFormat(e.target.value as RdfFormat)}
                className="rounded-md border border-gray-200 px-2 py-1 text-sm"
                data-testid="recall-format-select"
              >
                {FORMAT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-gray-700">
                Match threshold: <span className="tabular-nums">{threshold.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={0.5}
                max={1}
                step={0.01}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                data-testid="recall-threshold"
              />
              <span className="text-xs text-gray-500">
                Higher = stricter. 1.0 = exact post-normalisation match.
              </span>
            </label>

            <label className="flex items-center gap-2 text-sm self-end">
              <input
                type="checkbox"
                checked={includeProps}
                onChange={(e) => setIncludeProps(e.target.checked)}
                data-testid="recall-include-props"
              />
              <span>Include object properties</span>
            </label>
          </div>

          <div className="flex items-center justify-between gap-3 pt-2">
            <button
              onClick={runComparison}
              disabled={running || !referenceContent}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="recall-run-btn"
            >
              {running ? "Computing…" : "Compute recall"}
            </button>
            {error && (
              <p
                className="rounded-md bg-rose-50 px-3 py-1.5 text-xs text-rose-700"
                data-testid="recall-error"
              >
                {error}
              </p>
            )}
          </div>
        </section>

        {report && (
          <section
            className="space-y-6 border-t border-gray-100 bg-gray-50/40 px-6 py-5"
            data-testid="recall-report"
          >
            <div className="grid grid-cols-3 gap-4 sm:grid-cols-3">
              <ScoreTile label="Recall" value={report.summary.recall} />
              <ScoreTile label="Precision" value={report.summary.precision} />
              <ScoreTile label="F1" value={report.summary.f1} />
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs text-gray-500">
              <div>
                Reference concepts: <strong>{report.summary.reference_count}</strong>
              </div>
              <div>
                Extracted concepts: <strong>{report.summary.extracted_count}</strong>
              </div>
              <div>
                Matched: <strong>{report.summary.matched_count}</strong>
              </div>
            </div>

            <RecallSectionView title="Classes" section={report.classes} />
            {report.object_properties && (
              <RecallSectionView
                title="Object Properties"
                section={report.object_properties}
              />
            )}
          </section>
        )}
      </div>
    </div>
  );
}

function ScoreTile({ label, value }: { label: string; value: number }) {
  const color =
    value >= 0.8
      ? "text-emerald-600"
      : value >= 0.5
        ? "text-amber-600"
        : "text-rose-600";
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-gray-400">{label}</div>
      <div className={`mt-1 text-3xl font-bold tabular-nums ${color}`}>
        {pct(value)}
      </div>
    </div>
  );
}

function RecallSectionView({
  title,
  section,
}: {
  title: string;
  section: RecallSection;
}) {
  return (
    <details
      className="rounded-xl border border-gray-200 bg-white"
      data-testid={`recall-section-${title.toLowerCase().replace(/ /g, "-")}`}
    >
      <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-sm">
        <span className="font-semibold text-gray-700">{title}</span>
        <span className="text-xs text-gray-500">
          {section.summary.matched_count} matched · {section.missed.length} missed ·{" "}
          {section.false_positives.length} extra
        </span>
      </summary>
      <div className="grid gap-4 border-t border-gray-100 px-4 py-3 md:grid-cols-3">
        <Column heading={`Matched (${section.matched.length})`}>
          {section.matched.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1">
              {section.matched.map((m) => (
                <li
                  key={`${m.reference_uri}|${m.extracted_uri ?? ""}`}
                  className="text-xs text-gray-700"
                >
                  <span className="font-medium">{m.reference_label}</span>
                  <span className="text-gray-400"> ↔ </span>
                  <span>{m.extracted_label ?? "—"}</span>
                  <span className="ml-1 text-[10px] text-gray-400">
                    ({m.similarity.toFixed(2)})
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Column>
        <Column heading={`Missed (${section.missed.length})`}>
          {section.missed.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1">
              {section.missed.map((m) => (
                <li
                  key={m.reference_uri}
                  className="text-xs text-rose-700"
                  data-testid="recall-missed-row"
                >
                  {m.reference_label}
                </li>
              ))}
            </ul>
          )}
        </Column>
        <Column heading={`Extras (${section.false_positives.length})`}>
          {section.false_positives.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1">
              {section.false_positives.map((f, i) => (
                <li
                  key={f.extracted_uri ?? `fp_${i}`}
                  className="text-xs text-amber-700"
                  data-testid="recall-fp-row"
                >
                  {f.extracted_label ?? "—"}
                </li>
              ))}
            </ul>
          )}
        </Column>
      </div>
    </details>
  );
}

function Column({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
        {heading}
      </p>
      {children}
    </div>
  );
}

function Empty() {
  return <p className="text-xs italic text-gray-400">None</p>;
}
