/**
 * @jest-environment jsdom
 *
 * Client-side pre-check for the H.16 drag-and-drop import flow. The
 * tests pin three things:
 *
 *  1. Each rejection branch (no-canvas / self-import / duplicate) fires
 *     with the right ``reason`` and a user-facing ``message`` that
 *     names the dragged ontology when we have it.
 *  2. Missing / empty ``effectiveSources`` is treated as "unknown" —
 *     we let the backend catch it rather than blocking optimistically.
 *  3. ``DataTransfer`` round-trips through writeImportDragPayload /
 *     readImportDragPayload, and bogus drags (foreign MIME, malformed
 *     JSON, missing fields) return ``null`` instead of throwing so the
 *     drop handler stays defensive.
 */

import {
  IMPORT_DRAG_MIME,
  checkImportDragCandidate,
  readImportDragPayload,
  writeImportDragPayload,
} from "@/lib/importDragCheck";
import type { EffectiveSource } from "@/types/curation";

function src(key: string, depth = 1, isSelf = false): EffectiveSource {
  return {
    _key: key,
    name: key,
    is_self: isSelf,
    depth,
  };
}

describe("checkImportDragCandidate", () => {
  it("accepts a clean candidate (different ontology, not in closure)", () => {
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "foaf",
      draggedOntologyName: "FOAF",
      effectiveSources: [src("wtw", 0, true)],
    });
    expect(result.ok).toBe(true);
  });

  it("rejects with no-canvas when no ontology is open", () => {
    const result = checkImportDragCandidate({
      currentOntologyId: null,
      draggedOntologyId: "foaf",
      draggedOntologyName: "FOAF",
      effectiveSources: [],
    });
    expect(result).toEqual({
      ok: false,
      reason: "no-canvas",
      message: expect.stringMatching(/open an ontology first/i),
    });
  });

  it("rejects with self-import when dragged equals current", () => {
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "wtw",
      draggedOntologyName: "WTW Ontology",
      effectiveSources: [src("wtw", 0, true)],
    });
    expect(result).toEqual({
      ok: false,
      reason: "self-import",
      message: expect.stringContaining('"WTW Ontology"'),
    });
  });

  it("rejects with duplicate when target is already in the closure", () => {
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "foaf",
      draggedOntologyName: "FOAF",
      effectiveSources: [src("wtw", 0, true), src("foaf", 1)],
    });
    expect(result).toEqual({
      ok: false,
      reason: "duplicate",
      message: expect.stringMatching(/already imported.*directly or transitively/i),
    });
  });

  it("treats deep transitive matches as duplicate too", () => {
    // foaf is imported by an ontology we already import, depth=2. The
    // wire format puts every transitive ancestor in sources[], so the
    // pre-check catches diamond imports without an extra round-trip.
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "foaf",
      draggedOntologyName: "FOAF",
      effectiveSources: [
        src("wtw", 0, true),
        src("intermediate", 1),
        src("foaf", 2),
      ],
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("duplicate");
  });

  it("falls through to ok when effectiveSources is null (not yet loaded)", () => {
    // Effective payload still in flight -- we don't have the closure
    // yet. Optimistic accept; backend will reject if the import is
    // bad.
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "foaf",
      draggedOntologyName: "FOAF",
      effectiveSources: null,
    });
    expect(result.ok).toBe(true);
  });

  it("uses the dragged id when name is missing or blank", () => {
    const result = checkImportDragCandidate({
      currentOntologyId: "wtw",
      draggedOntologyId: "wtw",
      draggedOntologyName: "   ",
      effectiveSources: [src("wtw", 0, true)],
    });
    if (result.ok) throw new Error("expected rejection");
    expect(result.message).toContain('"wtw"');
  });
});

describe("writeImportDragPayload / readImportDragPayload", () => {
  function makeTransfer(): DataTransfer {
    // jsdom provides a stub DataTransfer in recent versions, but we
    // construct a minimal shape directly so the test is independent of
    // jsdom's coverage of the spec.
    const store = new Map<string, string>();
    return {
      setData: (mime: string, value: string) => {
        store.set(mime, value);
      },
      getData: (mime: string) => store.get(mime) ?? "",
      effectAllowed: "none",
      types: [] as readonly string[],
    } as unknown as DataTransfer;
  }

  it("round-trips a payload through write/read", () => {
    const t = makeTransfer();
    writeImportDragPayload(t, { ontologyId: "wtw", ontologyName: "WTW" });
    expect(t.effectAllowed).toBe("copy");
    expect(readImportDragPayload(t)).toEqual({
      ontologyId: "wtw",
      ontologyName: "WTW",
    });
  });

  it("uses the canonical MIME so source + target cannot drift", () => {
    expect(IMPORT_DRAG_MIME).toBe("application/x-aoe-ontology");
    const t = makeTransfer();
    writeImportDragPayload(t, { ontologyId: "x", ontologyName: "x" });
    expect(t.getData(IMPORT_DRAG_MIME)).toContain('"ontologyId"');
  });

  it("returns null when the MIME is absent (foreign drag)", () => {
    const t = makeTransfer();
    expect(readImportDragPayload(t)).toBeNull();
  });

  it("returns null on malformed JSON without throwing", () => {
    const t = makeTransfer();
    t.setData(IMPORT_DRAG_MIME, "{not json");
    expect(readImportDragPayload(t)).toBeNull();
  });

  it("returns null when required fields are missing or wrong type", () => {
    const t = makeTransfer();
    t.setData(IMPORT_DRAG_MIME, JSON.stringify({ ontologyId: "x" }));
    expect(readImportDragPayload(t)).toBeNull();

    const t2 = makeTransfer();
    t2.setData(
      IMPORT_DRAG_MIME,
      JSON.stringify({ ontologyId: 42, ontologyName: "x" }),
    );
    expect(readImportDragPayload(t2)).toBeNull();
  });
});
