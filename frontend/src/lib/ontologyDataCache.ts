/**
 * Module-level cache for ontology graph data (classes, edges, properties).
 *
 * Why this exists
 * ---------------
 *
 * The workspace originally re-fetched ``/classes`` and ``/edges`` from
 * scratch every time the user selected an ontology. Switching from WTW
 * to Financial Services and back meant pulling 360 KB + 445 KB over the
 * WAN twice for the WTW Ontology -- ~5-6 s the user pays for data they
 * literally just had a moment ago. T1.1 / T1.4 shrunk per-request
 * payload and killed the click-N+1, but they did nothing for the
 * back-and-forth case.
 *
 * Design
 * ------
 *
 * * **Module-level Map** keyed on ``ontologyId : kind : profile`` so
 *   the whole app shares one cache. Both ``workspace/page.tsx`` and
 *   ``AssetExplorer.tsx`` populate and read it -- the asset explorer's
 *   class list and the canvas's class list are the same data, and now
 *   the same cache entry.
 *
 * * **In-flight dedup**: if a fetch for a key is already in progress,
 *   a second concurrent caller (e.g. the canvas and the explorer
 *   firing simultaneously on a fresh ontology selection) waits on the
 *   same promise rather than issuing a duplicate request.
 *
 * * **No TTL** -- entries live until explicit invalidation. With
 *   summary projections at ~800 KB per ontology and a typical
 *   workspace seeing 3-10 ontologies in a session, total memory is
 *   bounded at single-digit MB. If that ever becomes a problem we add
 *   an LRU bound here without changing callers.
 *
 * * **Invalidation is mutation-driven**: callers that mutate ontology
 *   state (approve, reject, delete, edit) call
 *   ``invalidateOntology`` or ``invalidateOntologyKind`` to drop the
 *   stale entries. We deliberately do NOT use a TTL because TTL'd
 *   caches show stale data for the TTL window, which is the worst of
 *   both worlds for a tool whose value proposition is "trustworthy
 *   live view of the ontology". Cross-tab mutation is out of scope --
 *   AOE is currently a single-user tool.
 *
 * * **Structural cloning is the caller's problem**. We hand back the
 *   same object reference we cached, so callers must not mutate
 *   responses in place. (None of the current call sites do; React
 *   state setters are pure replace.)
 *
 * Not using SWR or React Query
 * ----------------------------
 *
 * Both libraries would solve the immediate problem but bring a
 * dependency, a hook-based API surface, and a model (focus
 * revalidation, error retry orchestration, cache devtools) that we
 * don't need yet. ~70 lines of code is the right footprint for the
 * current requirement -- if we later need things like background
 * revalidation we can swap to SWR without changing the imperative
 * call sites.
 */

type Kind = "classes" | "edges" | "properties";
type Profile = "summary" | "full";

interface CacheEntry<T> {
  data: T;
  /** When this entry was inserted (epoch ms). For diagnostics only -- the
   *  cache itself does not expire entries by age. */
  cachedAt: number;
}

/** ``${ontologyId}:${kind}:${profile}``. Keep the format stable -- the
 *  ``invalidateOntology`` prefix scan depends on it. */
type CacheKey = string;

const cache = new Map<CacheKey, CacheEntry<unknown>>();
const inflight = new Map<CacheKey, Promise<unknown>>();

function makeKey(ontologyId: string, kind: Kind, profile: Profile): CacheKey {
  return `${ontologyId}:${kind}:${profile}`;
}

/**
 * Fetch with cache + in-flight dedup.
 *
 * Order of operations:
 *   1. If we have a cached entry, return it synchronously (wrapped in a
 *      resolved Promise to keep the call signature uniform).
 *   2. If a fetch for this key is already in flight, return the existing
 *      promise so duplicate concurrent callers share one network round.
 *   3. Otherwise call the supplied ``fetcher``, store its result, and
 *      record it.
 *
 * On fetcher error the in-flight slot is cleared and the error
 * propagates -- the cache is NOT poisoned with a failure entry. The
 * caller decides whether to retry.
 */
export async function fetchOntologyData<T>(
  ontologyId: string,
  kind: Kind,
  profile: Profile,
  fetcher: () => Promise<T>,
): Promise<T> {
  const key = makeKey(ontologyId, kind, profile);

  const cached = cache.get(key);
  if (cached !== undefined) {
    return cached.data as T;
  }

  const existing = inflight.get(key);
  if (existing !== undefined) {
    return existing as Promise<T>;
  }

  const promise = fetcher()
    .then((data) => {
      cache.set(key, { data, cachedAt: Date.now() });
      inflight.delete(key);
      return data;
    })
    .catch((err: unknown) => {
      // Drop the in-flight entry so a retry fires a new request rather
      // than getting the rejected promise back forever.
      inflight.delete(key);
      throw err;
    });

  inflight.set(key, promise);
  return promise;
}

/**
 * Drop every cached entry for a given ontology, regardless of kind or
 * profile. Use after a structural change (new extraction run merged,
 * ontology edited, dedupe-edges run) where any kind could be stale.
 */
export function invalidateOntology(ontologyId: string): void {
  const prefix = `${ontologyId}:`;
  for (const key of [...cache.keys()]) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
  for (const key of [...inflight.keys()]) {
    if (key.startsWith(prefix)) inflight.delete(key);
  }
}

/**
 * Drop cached entries for a single ontology + kind, both profiles.
 *
 * Approve/reject of a single class invalidates ``classes`` only --
 * edges and properties for the same ontology are unaffected, so
 * scoping the invalidation here avoids unnecessary refetches.
 */
export function invalidateOntologyKind(ontologyId: string, kind: Kind): void {
  const prefix = `${ontologyId}:${kind}:`;
  for (const key of [...cache.keys()]) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
  for (const key of [...inflight.keys()]) {
    if (key.startsWith(prefix)) inflight.delete(key);
  }
}

/** Drop the entire cache. Used by the ``logout`` flow and tests. */
export function clearOntologyCache(): void {
  cache.clear();
  inflight.clear();
}

/**
 * Diagnostic-only view of cache state. Returns a fresh array so callers
 * cannot mutate the underlying maps. Intended for the in-page debug
 * panel and the test suite -- no production code branches on this.
 */
export function getOntologyCacheStats(): {
  size: number;
  inflightCount: number;
  entries: { key: string; ageMs: number }[];
} {
  const now = Date.now();
  const entries: { key: string; ageMs: number }[] = [];
  for (const [key, entry] of cache.entries()) {
    entries.push({ key, ageMs: now - entry.cachedAt });
  }
  return {
    size: cache.size,
    inflightCount: inflight.size,
    entries,
  };
}
