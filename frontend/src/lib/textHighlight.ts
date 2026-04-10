/**
 * Split text for keyword highlighting using a single capturing group.
 * Odd-index segments are matches (case-insensitive), even-index are plain text.
 */
export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function splitTextByKeywordAlternation(text: string, terms: string[]): string[] {
  const cleaned = terms.map((t) => t.trim()).filter((t) => t.length >= 2);
  if (cleaned.length === 0) return [text];
  const inner = cleaned.map(escapeRegExp).join("|");
  if (!inner) return [text];
  return text.split(new RegExp(`(${inner})`, "gi"));
}

/** Terms: full label plus significant words (matches workspace HighlightedText). */
export function termsFromEntityLabel(label: string): string[] {
  const trimmed = label.trim();
  const terms: string[] = [];
  if (trimmed.length >= 2) terms.push(trimmed);
  const words = trimmed.split(/\s+/).filter((w) => w.length >= 3);
  for (const w of words) {
    if (!terms.some((t) => t.toLowerCase() === w.toLowerCase())) terms.push(w);
  }
  return terms;
}
