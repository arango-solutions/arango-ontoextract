import { documentKey } from "@/lib/arangoId";
import type { OntologyEdge } from "@/types/curation";

export { documentKey };

/** Property→class edges: not drawn as class↔class links (PGT / legacy). */
export const FILTERED_FROM_CLASS_GRAPH = new Set(["rdfs_domain", "has_property"]);

/** Shown on synthetic domain→range edges when the API omits `edge.label`. */
export const RDFS_RANGE_CLASS_LABEL_FALLBACK = "owl:ObjectProperty";

export function getEdgeType(edge: OntologyEdge): string {
  return ((edge as unknown as Record<string, unknown>).edge_type ?? edge.type) as string;
}

export function isRelationshipEdgeStyle(edgeType: string): boolean {
  return edgeType === "related_to" || edgeType === "rdfs_range_class";
}

export interface SyntheticRdfsRangeEdge {
  edgeKey: string;
  sourceClassKey: string;
  targetClassKey: string;
  label: string;
}

/**
 * For each `rdfs_range_class` edge, resolve domain class via matching `rdfs_domain` on the same property `_from`.
 */
export function buildSyntheticRdfsRangeClassEdges(
  edges: OntologyEdge[],
  classKeySet: Set<string>,
): SyntheticRdfsRangeEdge[] {
  const propertyIdToDomainClassKey = new Map<string, string>();
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_domain") continue;
    propertyIdToDomainClassKey.set(edge._from, documentKey(edge._to));
  }

  const out: SyntheticRdfsRangeEdge[] = [];
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_range_class") continue;
    const domainClassKey = propertyIdToDomainClassKey.get(edge._from);
    if (!domainClassKey) continue;
    const rangeClassKey = documentKey(edge._to);
    if (!classKeySet.has(domainClassKey) || !classKeySet.has(rangeClassKey)) continue;
    const label =
      (edge.label && edge.label.trim()) || RDFS_RANGE_CLASS_LABEL_FALLBACK;
    out.push({
      edgeKey: edge._key,
      sourceClassKey: domainClassKey,
      targetClassKey: rangeClassKey,
      label,
    });
  }
  return out;
}
