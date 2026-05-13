import {
  clearOntologyCache,
  fetchOntologyData,
  getOntologyCacheStats,
  invalidateOntology,
  invalidateOntologyKind,
} from "../ontologyDataCache";

beforeEach(() => {
  clearOntologyCache();
});

describe("ontologyDataCache.fetchOntologyData", () => {
  it("calls the fetcher on first miss and returns its value", async () => {
    const fetcher = jest.fn().mockResolvedValue({ data: ["cls1"] });
    const out = await fetchOntologyData("ont1", "classes", "summary", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(out).toEqual({ data: ["cls1"] });
  });

  it("returns the cached value on a hit without calling the fetcher", async () => {
    const fetcher = jest.fn().mockResolvedValue({ data: ["cls1"] });
    await fetchOntologyData("ont1", "classes", "summary", fetcher);

    // Second call with a fetcher that would explode -- proving we never
    // hit it. This is the back-and-forth-between-ontologies case.
    const second = await fetchOntologyData("ont1", "classes", "summary", () => {
      throw new Error("fetcher must not be called on cache hit");
    });
    expect(second).toEqual({ data: ["cls1"] });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("returns identity-equal cached object on hit (no copy)", async () => {
    // Document the contract: the cache hands back the same reference.
    // Callers must not mutate -- React state setters are pure replace
    // so this is safe for the current call sites.
    const value = { data: ["cls1"] };
    await fetchOntologyData("ont1", "classes", "summary", () => Promise.resolve(value));
    const second = await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ different: true }) as unknown as Promise<typeof value>,
    );
    expect(second).toBe(value);
  });

  it("dedups concurrent fetches for the same key (single network round)", async () => {
    let resolve!: (v: { data: string[] }) => void;
    const fetcher = jest.fn().mockImplementation(
      () => new Promise<{ data: string[] }>((r) => { resolve = r; }),
    );

    const p1 = fetchOntologyData("ont1", "classes", "summary", fetcher);
    const p2 = fetchOntologyData("ont1", "classes", "summary", fetcher);
    const p3 = fetchOntologyData("ont1", "classes", "summary", fetcher);

    expect(fetcher).toHaveBeenCalledTimes(1);

    resolve({ data: ["cls1"] });
    const [a, b, c] = await Promise.all([p1, p2, p3]);
    expect(a).toBe(b);
    expect(b).toBe(c);
  });

  it("scopes by kind (classes and edges are independent caches)", async () => {
    const classesFetcher = jest.fn().mockResolvedValue({ data: ["cls1"] });
    const edgesFetcher = jest.fn().mockResolvedValue({ data: ["edge1"] });
    await fetchOntologyData("ont1", "classes", "summary", classesFetcher);
    await fetchOntologyData("ont1", "edges", "summary", edgesFetcher);
    expect(classesFetcher).toHaveBeenCalledTimes(1);
    expect(edgesFetcher).toHaveBeenCalledTimes(1);
  });

  it("scopes by profile (summary and full are independent caches)", async () => {
    const summary = jest.fn().mockResolvedValue({ data: ["summary"] });
    const full = jest.fn().mockResolvedValue({ data: ["full"] });
    const a = await fetchOntologyData("ont1", "classes", "summary", summary);
    const b = await fetchOntologyData("ont1", "classes", "full", full);
    expect(a).toEqual({ data: ["summary"] });
    expect(b).toEqual({ data: ["full"] });
    expect(summary).toHaveBeenCalledTimes(1);
    expect(full).toHaveBeenCalledTimes(1);
  });

  it("scopes by ontology id (other ontologies do not see each other's cache)", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["one"] }),
    );
    const other = await fetchOntologyData("ont2", "classes", "summary", () =>
      Promise.resolve({ data: ["two"] }),
    );
    expect(other).toEqual({ data: ["two"] });
  });

  it("does NOT cache failed fetches (next call retries)", async () => {
    const fetcher = jest
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ data: ["recovered"] });

    await expect(
      fetchOntologyData("ont1", "classes", "summary", fetcher),
    ).rejects.toThrow("network down");

    const ok = await fetchOntologyData("ont1", "classes", "summary", fetcher);
    expect(ok).toEqual({ data: ["recovered"] });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("clears the inflight slot on rejection so retry starts a new request", async () => {
    // Regression guard: a previous design left rejected promises in the
    // inflight map, so all subsequent callers got the same rejection forever.
    const fetcher = jest.fn().mockRejectedValue(new Error("boom"));
    await expect(
      fetchOntologyData("ont1", "classes", "summary", fetcher),
    ).rejects.toThrow();

    const stats = getOntologyCacheStats();
    expect(stats.inflightCount).toBe(0);
  });
});

describe("ontologyDataCache invalidation", () => {
  it("invalidateOntologyKind drops only that kind", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["c"] }),
    );
    await fetchOntologyData("ont1", "edges", "summary", () =>
      Promise.resolve({ data: ["e"] }),
    );

    invalidateOntologyKind("ont1", "classes");

    // classes refetched
    const classesFetcher = jest.fn().mockResolvedValue({ data: ["c2"] });
    await fetchOntologyData("ont1", "classes", "summary", classesFetcher);
    expect(classesFetcher).toHaveBeenCalledTimes(1);

    // edges still cached
    const edgesFetcher = jest.fn();
    await fetchOntologyData("ont1", "edges", "summary", edgesFetcher);
    expect(edgesFetcher).not.toHaveBeenCalled();
  });

  it("invalidateOntologyKind drops both summary and full profiles", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["c-sum"] }),
    );
    await fetchOntologyData("ont1", "classes", "full", () =>
      Promise.resolve({ data: ["c-full"] }),
    );

    invalidateOntologyKind("ont1", "classes");

    const summaryFetcher = jest.fn().mockResolvedValue({ data: ["new-sum"] });
    const fullFetcher = jest.fn().mockResolvedValue({ data: ["new-full"] });
    await fetchOntologyData("ont1", "classes", "summary", summaryFetcher);
    await fetchOntologyData("ont1", "classes", "full", fullFetcher);
    expect(summaryFetcher).toHaveBeenCalledTimes(1);
    expect(fullFetcher).toHaveBeenCalledTimes(1);
  });

  it("invalidateOntology drops every kind for that ontology", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["c"] }),
    );
    await fetchOntologyData("ont1", "edges", "summary", () =>
      Promise.resolve({ data: ["e"] }),
    );
    await fetchOntologyData("ont1", "properties", "summary", () =>
      Promise.resolve({ data: ["p"] }),
    );

    invalidateOntology("ont1");

    expect(getOntologyCacheStats().size).toBe(0);
  });

  it("invalidateOntology does NOT touch other ontologies", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["one"] }),
    );
    await fetchOntologyData("ont2", "classes", "summary", () =>
      Promise.resolve({ data: ["two"] }),
    );

    invalidateOntology("ont1");

    // ont2 should still be cached -- prove it by passing an exploding fetcher.
    const out = await fetchOntologyData("ont2", "classes", "summary", () => {
      throw new Error("fetcher must not be called");
    });
    expect(out).toEqual({ data: ["two"] });
  });

  it("clearOntologyCache empties everything", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: ["c"] }),
    );
    await fetchOntologyData("ont2", "edges", "full", () =>
      Promise.resolve({ data: ["e"] }),
    );
    clearOntologyCache();
    expect(getOntologyCacheStats().size).toBe(0);
  });
});

describe("ontologyDataCache.getOntologyCacheStats", () => {
  it("reports cached entries with non-negative age", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: [] }),
    );
    const stats = getOntologyCacheStats();
    expect(stats.size).toBe(1);
    expect(stats.entries[0].key).toBe("ont1:classes:summary");
    expect(stats.entries[0].ageMs).toBeGreaterThanOrEqual(0);
  });

  it("returns a copy, not the live map (callers cannot corrupt the cache)", async () => {
    await fetchOntologyData("ont1", "classes", "summary", () =>
      Promise.resolve({ data: [] }),
    );
    const stats = getOntologyCacheStats();
    stats.entries.length = 0;
    expect(getOntologyCacheStats().size).toBe(1);
  });
});
