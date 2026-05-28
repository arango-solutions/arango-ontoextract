import {
  api,
  backendUrl,
  buildApiUrl,
  fetchAllPages,
  getApiBaseUrl,
  getApiOrigin,
  type PaginatedPage,
} from "@/lib/api-client";

describe("buildApiUrl", () => {
  it("joins base and path when base has no /api/v1 suffix", () => {
    expect(buildApiUrl("http://localhost:8001", "/api/v1/ontology/library")).toBe(
      "http://localhost:8001/api/v1/ontology/library",
    );
  });

  it("deduplicates /api/v1 when base already ends with /api/v1", () => {
    expect(
      buildApiUrl("http://localhost:8001/api/v1", "/api/v1/ontology/library"),
    ).toBe("http://localhost:8001/api/v1/ontology/library");
  });
});

describe("backendUrl", () => {
  it("matches buildApiUrl(getApiBaseUrl(), path)", () => {
    expect(backendUrl("/ready")).toBe(buildApiUrl(getApiBaseUrl(), "/ready"));
    expect(backendUrl("/api/v1/auth/login")).toBe(
      buildApiUrl(getApiBaseUrl(), "/api/v1/auth/login"),
    );
  });
});

describe("getApiOrigin", () => {
  const prevApiUrl = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_URL = prevApiUrl;
  });

  it("returns window.location.origin when NEXT_PUBLIC_API_URL is a relative path (unified Docker image)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    // jsdom's default location is http://localhost
    expect(getApiOrigin()).toBe(window.location.origin);
    expect(getApiOrigin().startsWith("http")).toBe(true);
  });

  it("strips path component from absolute NEXT_PUBLIC_API_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com:9000/api/v1";
    expect(getApiOrigin()).toBe("https://api.example.com:9000");
  });

  it("never returns a value containing /api/v1 (would break ws:// URL construction)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    expect(getApiOrigin()).not.toContain("/api/v1");
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com/api/v1";
    expect(getApiOrigin()).not.toContain("/api/v1");
  });
});

describe("fetchAllPages", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("returns a single page's data when there is no next_cursor", async () => {
    const getSpy = jest
      .spyOn(api, "get")
      .mockResolvedValueOnce({ data: [1, 2, 3], next_cursor: null });

    const out = await fetchAllPages<number>((cursor) =>
      cursor ? `/p?cursor=${cursor}` : "/p",
    );

    expect(out).toEqual([1, 2, 3]);
    expect(getSpy).toHaveBeenCalledTimes(1);
    // First page is requested with a null cursor.
    expect(getSpy).toHaveBeenCalledWith("/p", { signal: undefined });
  });

  it("follows next_cursor across pages and concatenates in order", async () => {
    const pages: PaginatedPage<string>[] = [
      { data: ["a", "b"], next_cursor: "C1" },
      { data: ["c", "d"], next_cursor: "C2" },
      { data: ["e"], next_cursor: null },
    ];
    const getSpy = jest
      .spyOn(api, "get")
      .mockImplementation(async () => pages.shift() as PaginatedPage<string>);

    const paths: string[] = [];
    const out = await fetchAllPages<string>((cursor) => {
      const path = cursor ? `/p?cursor=${cursor}` : "/p";
      paths.push(path);
      return path;
    });

    expect(out).toEqual(["a", "b", "c", "d", "e"]);
    expect(getSpy).toHaveBeenCalledTimes(3);
    expect(paths).toEqual(["/p", "/p?cursor=C1", "/p?cursor=C2"]);
  });

  it("stops when a page returns the same cursor (no forward progress)", async () => {
    const getSpy = jest
      .spyOn(api, "get")
      // First page returns cursor "X"; second page echoes "X" again ->
      // the helper must stop rather than loop forever.
      .mockResolvedValueOnce({ data: [1], next_cursor: "X" })
      .mockResolvedValueOnce({ data: [2], next_cursor: "X" });

    const out = await fetchAllPages<number>((cursor) =>
      cursor ? `/p?cursor=${cursor}` : "/p",
    );

    expect(out).toEqual([1, 2]);
    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  it("respects the maxPages safety cap", async () => {
    // Server bug: always returns a fresh advancing cursor. The cap bounds it.
    let n = 0;
    const getSpy = jest.spyOn(api, "get").mockImplementation(async () => {
      n += 1;
      return { data: [n], next_cursor: `c${n}` };
    });

    const out = await fetchAllPages<number>(
      (cursor) => (cursor ? `/p?cursor=${cursor}` : "/p"),
      { maxPages: 3 },
    );

    expect(getSpy).toHaveBeenCalledTimes(3);
    expect(out).toEqual([1, 2, 3]);
  });

  it("threads the AbortSignal into every page request", async () => {
    const controller = new AbortController();
    const getSpy = jest
      .spyOn(api, "get")
      .mockResolvedValueOnce({ data: [1], next_cursor: "C1" })
      .mockResolvedValueOnce({ data: [2], next_cursor: null });

    await fetchAllPages<number>((cursor) => (cursor ? `/p?cursor=${cursor}` : "/p"), {
      signal: controller.signal,
    });

    for (const call of getSpy.mock.calls) {
      expect(call[1]).toEqual({ signal: controller.signal });
    }
  });

  it("tolerates a page with a missing/empty data array", async () => {
    jest
      .spyOn(api, "get")
      .mockResolvedValueOnce({ data: [], next_cursor: "C1" })
      .mockResolvedValueOnce({
        data: undefined as unknown as number[],
        next_cursor: null,
      });

    const out = await fetchAllPages<number>((cursor) =>
      cursor ? `/p?cursor=${cursor}` : "/p",
    );

    expect(out).toEqual([]);
  });
});

// `getBasePath` (formerly duplicated as `nextPublicBasePath` here) lives in
// `frontend/src/lib/base-path.ts`; see `__tests__/base-path.test.ts`.
