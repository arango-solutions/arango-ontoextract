/**
 * Pure helpers for the Stream 5 S.5 schema-diff workspace overlay.
 * Kept DB-free so counts / labels are unit-testable without React.
 */

export interface SchemaDiffSummary {
  classes_added: number;
  classes_removed: number;
  classes_changed: number;
  properties_added: number;
  properties_removed: number;
  properties_changed: number;
  constraints_added: number;
  constraints_removed: number;
  constraints_changed: number;
}

export interface SchemaDiffBucket<TAdded, TRemoved, TChanged> {
  added: TAdded[];
  removed: TRemoved[];
  changed: TChanged[];
}

export interface SchemaDiffEntityRow {
  uri?: string;
  label?: string;
  [key: string]: unknown;
}

export interface SchemaDiffChangedEntityRow {
  uri: string;
  before: SchemaDiffEntityRow;
  after: SchemaDiffEntityRow;
}

export interface SchemaDiffChangedConstraintRow {
  class_uri: string;
  property_uri: string;
  restriction_type: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface SchemaDiffResponse {
  ontology_a: string;
  ontology_b: string;
  classes: SchemaDiffBucket<SchemaDiffEntityRow, SchemaDiffEntityRow, SchemaDiffChangedEntityRow>;
  properties: SchemaDiffBucket<SchemaDiffEntityRow, SchemaDiffEntityRow, SchemaDiffChangedEntityRow>;
  constraints: SchemaDiffBucket<
    Record<string, unknown>,
    Record<string, unknown>,
    SchemaDiffChangedConstraintRow
  >;
  summary: SchemaDiffSummary;
  provenance: {
    a: Record<string, unknown>;
    b: Record<string, unknown>;
    compatible: boolean;
    warning: string | null;
  };
}

export interface RegistryOntologyOption {
  _key: string;
  name?: string;
}

/** Human-readable one-line summary for the overlay header. */
export function formatSchemaDiffSummaryLine(summary: SchemaDiffSummary): string {
  const parts: string[] = [];
  const push = (n: number, singular: string, plural: string) => {
    if (n > 0) parts.push(`${n} ${n === 1 ? singular : plural}`);
  };
  push(summary.classes_added, "class added", "classes added");
  push(summary.classes_removed, "class removed", "classes removed");
  push(summary.classes_changed, "class changed", "classes changed");
  push(summary.properties_added, "property added", "properties added");
  push(summary.properties_removed, "property removed", "properties removed");
  push(summary.properties_changed, "property changed", "properties changed");
  push(summary.constraints_added, "constraint added", "constraints added");
  push(summary.constraints_removed, "constraint removed", "constraints removed");
  push(summary.constraints_changed, "constraint changed", "constraints changed");
  if (parts.length === 0) return "No schema differences detected.";
  return parts.join(" · ");
}

/** Prefer label, fall back to URI tail, then raw uri. */
export function entityDiffLabel(row: { uri?: string; label?: string }): string {
  if (typeof row.label === "string" && row.label.trim()) return row.label.trim();
  if (typeof row.uri === "string" && row.uri.trim()) {
    const tail = row.uri.split(/[#/]/).filter(Boolean).pop();
    return tail ?? row.uri;
  }
  return "(unknown)";
}

export function constraintDiffLabel(row: SchemaDiffChangedConstraintRow): string {
  const prop = row.property_uri.split(/[#/]/).filter(Boolean).pop() ?? row.property_uri;
  return `${prop} (${row.restriction_type})`;
}

/** Block compare when A and B are the same registry key. */
export function validateSchemaDiffSelection(ontologyA: string, ontologyB: string): string | null {
  const a = ontologyA.trim();
  const b = ontologyB.trim();
  if (!a || !b) return "Select both ontologies to compare.";
  if (a === b) return "Choose two different ontologies.";
  return null;
}

export function registryDisplayName(entry: RegistryOntologyOption, fallbackKey?: string): string {
  const name = typeof entry.name === "string" ? entry.name.trim() : "";
  if (name) return name;
  return fallbackKey ?? entry._key;
}

/** Build the diff API URL (credentials-free GET). */
export function schemaDiffUrl(ontologyA: string, ontologyB: string): string {
  return (
    `/api/v1/ontology/schema/diff?a=${encodeURIComponent(ontologyA)}` +
    `&b=${encodeURIComponent(ontologyB)}`
  );
}
