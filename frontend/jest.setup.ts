import "@testing-library/jest-dom";
import { configure } from "@testing-library/dom";

// Async testing-library helpers (``findBy*``, ``waitFor``) default to a
// 1000 ms timeout. That is fine without coverage but the v8 coverage
// instrumentation we run in CI triples per-render cost in jsdom, so a
// chain of async state transitions (mount -> POST /run resolves ->
// fetchCandidates -> setRows([]) -> empty state renders) can push past
// the default and surface as a flake. 5000 ms is comfortable for the
// instrumented path and still small enough that a genuinely-stuck
// test fails quickly. Tests opt back into a tighter timeout per-call
// when they need to assert "X never appears".
configure({ asyncUtilTimeout: 5000 });

if (typeof globalThis.fetch === "undefined") {
  globalThis.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve("{}"),
      headers: new Headers(),
    }),
  ) as jest.Mock;
}
