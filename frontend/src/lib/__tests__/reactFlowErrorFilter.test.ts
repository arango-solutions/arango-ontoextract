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
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const again = require("@/lib/reactFlowErrorFilter").reactFlowErrorFilter;
    expect(again).toBe(reactFlowErrorFilter);
  });
});
