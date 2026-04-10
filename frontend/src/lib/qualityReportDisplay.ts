/**
 * Display helpers for GET /api/v1/quality/{ontology_id} payloads.
 * Backend mixes 0–1 ratios (avg_confidence, acceptance_rate) with 0–100 scores
 * (health_score, completeness, connectivity).
 */

export type QualityMetricRow = { label: string; value: string; color?: string };

function formatRatio0To1AsPercent(v: unknown): string | null {
  if (v == null) return null;
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${(n * 100).toFixed(1)}%`;
}

function formatScore0To100AsPercent(v: unknown): string | null {
  if (v == null) return null;
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toFixed(1)}%`;
}

/** Registry / list rows may store health as 0–1 or 0–100. */
export function formatOntologyHealthSummary(v: unknown): string | undefined {
  if (v == null) return undefined;
  const n = Number(v);
  if (Number.isNaN(n)) return undefined;
  if (n >= 0 && n <= 1.0001) return `${Math.round(n * 100)}%`;
  return `${Math.round(n)}%`;
}

function colorForRatio(n: number): string {
  if (Number.isNaN(n)) return "text-gray-600";
  if (n >= 0.7) return "text-green-600";
  if (n >= 0.5) return "text-yellow-600";
  return "text-red-600";
}

function colorForScore0To100(n: number): string {
  if (Number.isNaN(n)) return "text-gray-600";
  if (n >= 70) return "text-green-600";
  if (n >= 50) return "text-yellow-600";
  return "text-red-600";
}

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 120) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}m ${Math.round(r)}s`;
}

/**
 * Builds grid rows for the ontology quality API merge of ontology + extraction metrics.
 */
export function buildQualityReportMetrics(report: Record<string, unknown>): QualityMetricRow[] {
  const metrics: QualityMetricRow[] = [];

  const pushRatio = (label: string, v: unknown) => {
    const s = formatRatio0To1AsPercent(v);
    if (s == null) return;
    const n = Number(v);
    metrics.push({ label, value: s, color: colorForRatio(n) });
  };

  const pushPct100 = (label: string, v: unknown) => {
    const s = formatScore0To100AsPercent(v);
    if (s == null) return;
    const n = Number(v);
    metrics.push({ label, value: s, color: colorForScore0To100(n) });
  };

  if (report.health_score != null) {
    const s = formatScore0To100AsPercent(report.health_score);
    if (s != null) {
      const n = Number(report.health_score);
      metrics.push({ label: "Health Score", value: s, color: colorForScore0To100(n) });
    }
  }
  pushRatio("Avg Confidence", report.avg_confidence);
  pushRatio("Faithfulness", report.avg_faithfulness);
  pushRatio("Semantic Validity", report.avg_semantic_validity);
  pushPct100("Completeness", report.completeness);
  pushPct100("Connectivity", report.connectivity);

  if (report.class_count != null) {
    metrics.push({ label: "Classes", value: String(report.class_count) });
  }
  if (report.property_count != null) {
    metrics.push({ label: "Properties", value: String(report.property_count) });
  }
  if (report.classes_without_properties != null) {
    metrics.push({
      label: "Classes w/o properties",
      value: String(report.classes_without_properties),
    });
  }
  if (report.orphan_count != null) {
    metrics.push({ label: "Orphan Classes", value: String(report.orphan_count) });
  }
  if (report.has_cycles != null) {
    const c = report.has_cycles ? "text-red-600" : "text-green-600";
    metrics.push({
      label: "Has Cycles",
      value: report.has_cycles ? "Yes" : "No",
      color: c,
    });
  }
  if (report.relationship_count != null) {
    metrics.push({ label: "Relationships", value: String(report.relationship_count) });
  }
  pushRatio("Curation acceptance", report.acceptance_rate);
  if (report.time_to_ontology_ms != null) {
    const ms = Number(report.time_to_ontology_ms);
    if (!Number.isNaN(ms)) {
      metrics.push({ label: "Time to ontology", value: formatDurationMs(ms) });
    }
  }
  if (report.estimated_cost != null) {
    const c = Number(report.estimated_cost);
    if (!Number.isNaN(c)) {
      metrics.push({ label: "Extraction Cost", value: `$${c.toFixed(4)}` });
    }
  }

  const sm = report.schema_metrics;
  if (sm != null && typeof sm === "object" && !Array.isArray(sm)) {
    const keys = Object.keys(sm as Record<string, unknown>);
    if (keys.length > 0) {
      metrics.push({
        label: "Schema metrics",
        value: `${keys.length} fields (see API)`,
      });
    }
  }

  if (metrics.length === 0) {
    metrics.push({
      label: "Quality report",
      value: "No displayable fields in response",
    });
  }

  return metrics;
}
