/**
 * Shared stroke colors for the ontology graph (semantic lens and defaults).
 * Chosen for separation on dark (#111118) backgrounds — spread across hue.
 */
export const ONTOLOGY_EDGE_COLORS: Record<string, string> = {
  subclass_of: "#a78bfa",
  equivalent_class: "#f472b6",
  has_property: "#38bdf8",
  rdfs_domain: "#60a5fa",
  extends_domain: "#facc15",
  related_to: "#fb923c",
  rdfs_range_class: "#2dd4bf",
  extracted_from: "#4ade80",
  imports: "#f87171",
};

/** Ordered rows for CanvasLensLegend (semantic). */
export const SEMANTIC_EDGE_LEGEND: { edgeType: string; label: string }[] = [
  { edgeType: "subclass_of", label: "Subclass / hierarchy" },
  { edgeType: "equivalent_class", label: "Equivalent class" },
  { edgeType: "has_property", label: "Has property" },
  { edgeType: "rdfs_domain", label: "Property domain" },
  { edgeType: "extends_domain", label: "Extends domain" },
  { edgeType: "related_to", label: "Related to" },
  { edgeType: "rdfs_range_class", label: "Range → class" },
  { edgeType: "extracted_from", label: "Extracted from document" },
  { edgeType: "imports", label: "Imports" },
];
