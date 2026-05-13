import { reactFlowErrorFilter } from "@/lib/reactFlowErrorFilter";

describe("reactFlowErrorFilter", () => {
  let warnSpy: jest.SpyInstance;
  const prevEnv = process.env.NODE_ENV;

  beforeEach(() => {
    warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    // Force dev so the forwarding branch is exercised.
    Object.defineProperty(process.env, "NODE_ENV", {
      value: "development",
      configurable: true,
    });
  });

  afterEach(() => {
    warnSpy.mockRestore();
    Object.defineProperty(process.env, "NODE_ENV", {
      value: prevEnv,
      configurable: true,
    });
  });

  it("swallows the React 18 strict-mode false positive (code 002)", () => {
    reactFlowErrorFilter("002", "It looks like you've created a new nodeTypes…");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("forwards every other React Flow error code with the canonical prefix", () => {
    reactFlowErrorFilter("003", "Node type 'foo' not found");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    const [msg] = warnSpy.mock.calls[0];
    expect(msg).toContain("[React Flow]");
    expect(msg).toContain("Node type 'foo' not found");
    expect(msg).toContain("https://reactflow.dev/error#003");
  });

  it("does not forward in production (matches React Flow's devWarn behaviour)", () => {
    Object.defineProperty(process.env, "NODE_ENV", {
      value: "production",
      configurable: true,
    });
    reactFlowErrorFilter("003", "Node type 'foo' not found");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("is a stable module-scope reference (safe to pass as a React prop)", () => {
    // Re-importing must yield the same function identity.
    // Identity stability matters so passing it to <ReactFlow onError={...}>
    // does not itself trigger React Flow's prop-reference checks.
    const again = require("@/lib/reactFlowErrorFilter").reactFlowErrorFilter;
    expect(again).toBe(reactFlowErrorFilter);
  });
});

// ---------------------------------------------------------------------------
// Global console.warn shim -- catches React Flow's first-render `devWarn`
// path which bypasses the `onError` prop. See file header for rationale.
// ---------------------------------------------------------------------------

describe("React Flow 002 console.warn shim (installed at module load)", () => {
  // The shim wraps ``console.warn`` at import time and CAPTURES the
  // pre-shim writer as its ``original`` reference. To observe what
  // the shim forwards we therefore must:
  //
  //   1. Replace ``console.warn`` with a spy BEFORE the module loads.
  //   2. Reset the module cache so the next ``require`` re-runs the
  //      installer, which captures our spy as ``original``.
  //   3. Call the now-active shim (``console.warn``) and assert on
  //      the spy: a 002 message yields zero spy calls (swallowed),
  //      anything else yields exactly one (forwarded).
  //
  // This pattern is the only way to verify the shim's effect without
  // poking at private state -- it's the same dance any
  // monkeypatching test of a module-load side effect has to do.
  let writeSpy: jest.Mock;
  let realWarn: typeof console.warn;

  beforeEach(() => {
    realWarn = console.warn;
    writeSpy = jest.fn();
    // Step 1: install probe over real console.warn.
    console.warn = writeSpy;
    // Step 2: blow away the cached module so the installer runs
    // again and captures `writeSpy` as its `original` reference.
    jest.resetModules();
    require("@/lib/reactFlowErrorFilter");
    // Now console.warn === <shim-wrapped writeSpy>.
  });

  afterEach(() => {
    console.warn = realWarn;
    // Reset modules so a subsequent test gets the original installed
    // shim back without our test-only marker chain.
    jest.resetModules();
    require("@/lib/reactFlowErrorFilter");
  });

  it("swallows the React Flow 002 message even when emitted by devWarn directly", () => {
    // This is exactly the format React Flow's ``devWarn`` produces
    // for code 002 -- a single string argument prefixed with
    // ``[React Flow]:`` containing the canonical 002 sentence.
    console.warn(
      "[React Flow]: It looks like you've created a new nodeTypes or edgeTypes object. " +
        "If this wasn't on purpose please define the nodeTypes/edgeTypes outside of the " +
        "component or memoize them. Help: https://reactflow.dev/error#002",
    );
    // Shim swallowed it -> probe never invoked.
    expect(writeSpy).not.toHaveBeenCalled();
  });

  it("passes through unrelated warnings unchanged", () => {
    console.warn("Some unrelated warning about something else");
    expect(writeSpy).toHaveBeenCalledTimes(1);
    expect(writeSpy).toHaveBeenCalledWith(
      "Some unrelated warning about something else",
    );
  });

  it("passes through other React Flow codes (e.g. 008 edge-source-not-found)", () => {
    // Real diagnostics must NOT be silenced -- otherwise the shim
    // becomes a debugging hazard.
    console.warn(
      "[React Flow]: Couldn't create edge for source handle id... " +
        "Help: https://reactflow.dev/error#008",
    );
    expect(writeSpy).toHaveBeenCalledTimes(1);
  });

  it("passes through warnings whose first arg isn't a string (no false matches)", () => {
    const obj = { kind: "diagnostic", code: 42 };
    console.warn(obj, "trailing context");
    expect(writeSpy).toHaveBeenCalledTimes(1);
    expect(writeSpy).toHaveBeenCalledWith(obj, "trailing context");
  });

  it("is idempotent across re-imports (HMR safety)", () => {
    // Re-importing the module a second time must NOT stack another
    // wrapper on top of ``console.warn``; the shim's marker prop
    // detects an already-installed shim and bails out. Without this
    // guard, every dev-mode hot reload would add another forwarder
    // and one 002 message would be inspected (and swallowed) N
    // times -- harmless functionally but a memory + perf leak.
    //
    // We DELIBERATELY do NOT call jest.resetModules() here -- the
    // marker only protects against double-install when the module
    // re-imports without a cache clear, which is what real HMR
    // does.
    require("@/lib/reactFlowErrorFilter");
    console.warn(
      "[React Flow]: It looks like you've created a new nodeTypes or edgeTypes object. " +
        "Help: https://reactflow.dev/error#002",
    );
    expect(writeSpy).not.toHaveBeenCalled();
  });
});
