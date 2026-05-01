import { render, screen, waitFor } from "@testing-library/react";
import Home from "@/app/page";

const mockFetch = jest.fn();

beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
});

function stubHealthy() {
  mockFetch.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/ready")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: "ready", database: "connected" }),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: [], total_count: 3, has_more: false, cursor: null }),
      headers: new Headers({ "content-type": "application/json" }),
    });
  });
}

function stubDown() {
  mockFetch.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/ready")) {
      return Promise.resolve({
        ok: false,
        status: 502,
        json: () =>
          Promise.resolve({ status: "proxy_error", detail: "Cannot reach API" }),
      });
    }
    return Promise.reject(new TypeError("fetch failed"));
  });
}

describe("Home page", () => {
  it("renders the application heading", () => {
    stubHealthy();
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: /arango-ontoextract/i }),
    ).toBeInTheDocument();
  });

  it("renders the tagline", () => {
    stubHealthy();
    render(<Home />);
    expect(
      screen.getByText(/ontology extraction and curation platform/i),
    ).toBeInTheDocument();
  });

  it("shows Connected when backend is healthy", async () => {
    stubHealthy();
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeInTheDocument();
    });
  });

  it("shows Unavailable when backend is down", async () => {
    stubDown();
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("Unavailable")).toBeInTheDocument();
    });
  });

  it("displays ontology count from library endpoint", async () => {
    stubHealthy();
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("3")).toBeInTheDocument();
    });
  });

  it("calls /ready and library endpoints on mount", () => {
    stubHealthy();
    render(<Home />);
    expect(
      mockFetch.mock.calls.some(
        ([u]) => typeof u === "string" && u.endsWith("/ready"),
      ),
    ).toBe(true);
    const libraryCalls = mockFetch.mock.calls.filter(
      ([url]: [string]) =>
        typeof url === "string" && url.includes("/api/v1/ontology/library"),
    );
    expect(libraryCalls.length).toBeGreaterThanOrEqual(1);
  });
});
