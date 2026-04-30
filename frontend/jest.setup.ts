import "@testing-library/jest-dom";
import { jest } from "@jest/globals";

if (typeof globalThis.fetch === "undefined") {
  globalThis.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve("{}"),
      headers: new Headers(),
    }),
  ) as unknown as typeof fetch;
}
