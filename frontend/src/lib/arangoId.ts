/** Helpers for working with ArangoDB document identifiers. */

/**
 * Extract the document `_key` from a full Arango `_id` (`collection/key`).
 *
 * Edges carry `_from` / `_to` as full `_id`s; the UI almost always wants just
 * the key half. Falls back to the input unchanged when there is no `/`, so a
 * bare key passes through untouched.
 */
export function documentKey(fullId: string): string {
  return fullId.split("/").pop() ?? fullId;
}
