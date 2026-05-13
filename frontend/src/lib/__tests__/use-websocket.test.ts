import { act, renderHook, waitFor } from "@testing-library/react";
import {
  TERMINAL_RUN_STATUSES,
  probeRunStatus,
  resolveWsUrl,
  useExtractionSocket,
} from "@/lib/use-websocket";

describe("resolveWsUrl", () => {
  const prevApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const prevBasePath = process.env.NEXT_PUBLIC_BASE_PATH;

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_URL = prevApiUrl;
    process.env.NEXT_PUBLIC_BASE_PATH = prevBasePath;
    localStorage.clear();
  });

  it("produces wss://host/ws/... when NEXT_PUBLIC_API_URL is a relative /api/v1 (unified image regression)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    const url = resolveWsUrl("run-123");
    expect(url).toMatch(/^wss?:\/\//);
    expect(url).not.toContain("/api/v1/ws/");
    expect(url).toContain("/ws/extraction/run-123");
  });

  it("strips path component from absolute NEXT_PUBLIC_API_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com:9000/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    expect(resolveWsUrl("abc")).toBe("wss://api.example.com:9000/ws/extraction/abc");
  });

  it("includes NEXT_PUBLIC_BASE_PATH so SERVICE_URL_PATH_PREFIX deployments reach the backend strip middleware", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://host.test/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "/_service/uds/_db/aoe/svc";
    expect(resolveWsUrl("r1")).toBe(
      "wss://host.test/_service/uds/_db/aoe/svc/ws/extraction/r1",
    );
  });

  it("appends auth token from localStorage", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://host.test";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    localStorage.setItem("aoe_auth_token", "tok+/=&");
    expect(resolveWsUrl("r1")).toBe(
      "wss://host.test/ws/extraction/r1?token=tok%2B%2F%3D%26",
    );
  });

  it("returns empty string in SSR context (no window)", () => {
    const origWindow = global.window;
    // @ts-expect-error simulate SSR
    delete global.window;
    try {
      expect(resolveWsUrl("r1")).toBe("");
    } finally {
      global.window = origWindow;
    }
  });
});

// ---------------------------------------------------------------------------
// TERMINAL_RUN_STATUSES -- the gating set used by useExtractionSocket
// ---------------------------------------------------------------------------

describe("TERMINAL_RUN_STATUSES", () => {
  // These two sets tell the WS hook "no point opening a socket". If a
  // future status string lands on the backend (e.g. "succeeded"), the
  // hook will conservatively try to open WS for it -- which is the
  // safe fallback (empty broadcaster vs. missing live data) but means
  // we want to add it here when we know it. Pinning the exact
  // membership protects against accidental drift.
  it("includes the four terminal statuses the backend currently emits", () => {
    expect(TERMINAL_RUN_STATUSES.has("completed")).toBe(true);
    expect(TERMINAL_RUN_STATUSES.has("completed_with_errors")).toBe(true);
    expect(TERMINAL_RUN_STATUSES.has("failed")).toBe(true);
    expect(TERMINAL_RUN_STATUSES.has("cancelled")).toBe(true);
    expect(TERMINAL_RUN_STATUSES.has("skipped")).toBe(true);
  });

  it("does NOT include in-flight statuses (else WS would never open)", () => {
    expect(TERMINAL_RUN_STATUSES.has("running")).toBe(false);
    expect(TERMINAL_RUN_STATUSES.has("queued")).toBe(false);
    expect(TERMINAL_RUN_STATUSES.has("paused")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// probeRunStatus -- best-effort GET /runs/{id} → status string | null
// ---------------------------------------------------------------------------

describe("probeRunStatus", () => {
  const realFetch = global.fetch;

  afterEach(() => {
    global.fetch = realFetch;
  });

  it("returns the status string on a 200 with a status field", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "running", _key: "r1" }),
    });
    expect(await probeRunStatus("r1")).toBe("running");
  });

  it("returns null on non-200 (so caller falls through to opening WS)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: false, json: () => Promise.resolve({}) });
    expect(await probeRunStatus("missing")).toBeNull();
  });

  it("returns null when fetch throws (network blip / backend down)", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    expect(await probeRunStatus("r1")).toBeNull();
  });

  it("returns null when the run document has no status field", async () => {
    // Defensive: an oddly-shaped backend response should not crash
    // the WS gate; falling through to "open WS" is the safer default.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ _key: "r1" }),
    });
    expect(await probeRunStatus("r1")).toBeNull();
  });

  it("returns null when status is non-string (defensive)", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 200 }),
    });
    expect(await probeRunStatus("r1")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// useExtractionSocket -- WS connection gating
// ---------------------------------------------------------------------------
// The hook is the public surface that the Pipeline Monitor uses. The
// behaviour we MUST lock in here is:
//
//   * Terminal runs don't open a WebSocket. (Otherwise the slider
//     scrubbing through completed runs in the WTW-Ontology demo
//     opens dozens of doomed sockets, exhausts the browser's
//     per-origin connection cap, floods the console with "WebSocket
//     is closed before the connection is established" errors, and
//     starves the page event loop until the slider stops responding.)
//   * Active runs DO open a WebSocket immediately so live progress
//     is visible.
//   * If the status probe blips (network, backend restart), we open
//     the WS anyway -- a brief retry storm is preferable to silently
//     denying real-time visibility on an actually-running pipeline.
//
// We mock the WebSocket constructor with a Jest spy and assert on
// call counts; this is more robust than poking the hook's internal
// readyState flags and survives the React 18 strict-mode double
// effect run because the hook's cancellation flag short-circuits
// the second probe before it can spawn a stale socket.

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
  }
  close() {
    this.readyState = MockWebSocket.CLOSED;
  }
}

describe("useExtractionSocket -- WS gating", () => {
  const realFetch = global.fetch;
  const realWebSocket = global.WebSocket;
  let wsCtor: jest.Mock;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8010";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    wsCtor = jest.fn().mockImplementation((url: string) => new MockWebSocket(url));
    // @ts-expect-error -- jest spy doesn't match the lib's WebSocket type
    global.WebSocket = wsCtor;
  });

  afterEach(() => {
    global.fetch = realFetch;
    global.WebSocket = realWebSocket;
    jest.clearAllMocks();
  });

  function mockStatus(status: string) {
    // The hook also runs a REST poll effect that calls
    // ``fetchStepsFromRest`` on the same endpoint -- both go to
    // ``/runs/{id}``. Returning a stable response covers both paths
    // without mocking each call site separately.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status,
          _key: "r1",
          stats: { step_logs: [] },
        }),
    });
  }

  it("does NOT open a WebSocket for a completed run", async () => {
    mockStatus("completed");
    const { unmount } = renderHook(() => useExtractionSocket("r1"));
    // The status probe is async (one microtask + one fetch tick). Wait
    // for the gate decision to settle before asserting.
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    // Give any erroneously-queued connect() a tick to fire so the
    // assertion isn't racing.
    await act(async () => {
      await Promise.resolve();
    });
    expect(wsCtor).not.toHaveBeenCalled();
    unmount();
  });

  it("does NOT open a WebSocket for failed / cancelled / completed_with_errors", async () => {
    for (const terminal of [
      "failed",
      "cancelled",
      "completed_with_errors",
      "skipped",
    ]) {
      mockStatus(terminal);
      const { unmount } = renderHook(() => useExtractionSocket("r1"));
      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalled();
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(wsCtor).not.toHaveBeenCalled();
      unmount();
      jest.clearAllMocks();
    }
  });

  it("OPENS a WebSocket for an active run (running)", async () => {
    mockStatus("running");
    const { unmount } = renderHook(() => useExtractionSocket("r1"));
    await waitFor(() => {
      expect(wsCtor).toHaveBeenCalledTimes(1);
    });
    expect(wsCtor.mock.calls[0][0]).toContain("/ws/extraction/r1");
    unmount();
  });

  it("OPENS a WebSocket for queued / paused runs", async () => {
    for (const active of ["queued", "paused"]) {
      mockStatus(active);
      const { unmount } = renderHook(() => useExtractionSocket("r1"));
      await waitFor(() => {
        expect(wsCtor).toHaveBeenCalled();
      });
      unmount();
      jest.clearAllMocks();
    }
  });

  it("OPENS a WebSocket when status probe FAILS (defensive fallback)", async () => {
    // Network blip / backend restart shouldn't deny live visibility
    // on what might be a real running pipeline -- safer to attempt
    // the WS than to silently treat it as terminal.
    global.fetch = jest.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    const { unmount } = renderHook(() => useExtractionSocket("r1"));
    await waitFor(() => {
      expect(wsCtor).toHaveBeenCalled();
    });
    unmount();
  });

  it("does NOT open WebSocket when runId is null", async () => {
    mockStatus("running");
    const { unmount } = renderHook(() => useExtractionSocket(null));
    // Give any background work a tick to NOT fire.
    await act(async () => {
      await Promise.resolve();
    });
    expect(wsCtor).not.toHaveBeenCalled();
    unmount();
  });

  it("does NOT open a stale WebSocket when runId changes mid-probe", async () => {
    // Slider scrub case: user clicks run A (terminal) then run B
    // (terminal) before A's status probe resolves. With the
    // cancellation flag in place, neither probe should result in a
    // WS being opened. Without the flag, A's late-resolving probe
    // would have triggered connect() against the stale runId.
    let resolveProbeA: (v: unknown) => void = () => {};
    const probeAPromise = new Promise((r) => {
      resolveProbeA = r;
    });
    global.fetch = jest
      .fn()
      .mockImplementationOnce(() => probeAPromise) // A: never resolves until we say
      .mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            status: "completed",
            _key: "B",
            stats: { step_logs: [] },
          }),
      });

    const { rerender, unmount } = renderHook(
      ({ id }: { id: string | null }) => useExtractionSocket(id),
      { initialProps: { id: "A" as string | null } },
    );

    // Switch to B before A's probe resolves.
    rerender({ id: "B" });

    // Now resolve A late -- the cancellation flag should prevent it
    // from opening a WS for the now-stale runId.
    await act(async () => {
      resolveProbeA({
        ok: true,
        json: () =>
          Promise.resolve({
            status: "completed",
            _key: "A",
            stats: { step_logs: [] },
          }),
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(wsCtor).not.toHaveBeenCalled();
    unmount();
  });
});
