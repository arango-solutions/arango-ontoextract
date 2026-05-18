/**
 * Tests for the Upload page's Base Ontologies multi-select (Stream 1 H.8).
 *
 * Scope: the new selector's visibility, target-exclusion behaviour, and
 * that `base_ontology_ids` makes it onto the `/api/v1/extraction/run`
 * POST body. The wider upload page (drag-drop, OWL import mode, polling)
 * already has working flows; we are pinning down the H.8 surface only.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockApiGet = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => mockApiGet(...args),
  },
  backendUrl: (path: string) => `http://test${path}`,
}));

jest.mock("@/lib/base-path", () => ({
  withBasePath: (p: string) => p,
}));

// The page renders the Next.js `<Link>` and `<a>` for navigation;
// jsdom is happy with `<a>` so no shim is required for `<Link>` --
// but the production component imports `next/link`, so map it to a
// trivial passthrough.
jest.mock("next/link", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => children,
}));

const _originalFetch = global.fetch;

const FOAF: { _key: string; name: string; class_count: number; tier: string } = {
  _key: "foaf",
  name: "FOAF",
  class_count: 16,
  tier: "core",
};
const DCTERMS = { _key: "dcterms", name: "DCMI Terms", class_count: 0, tier: "core" };
const ACME = { _key: "acme", name: "Acme Domain", class_count: 42, tier: "domain" };

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/ontology/library")) {
      return { data: [FOAF, DCTERMS, ACME] };
    }
    if (path === "/api/v1/documents") {
      return {
        data: [
          {
            _key: "doc-1",
            filename: "spec.pdf",
            status: "ready",
            mime_type: "application/pdf",
            upload_date: "2026-05-15T00:00:00Z",
            chunk_count: 4,
          },
        ],
      };
    }
    if (path.startsWith("/api/v1/documents/") && path.endsWith("/ontologies")) {
      return { ontologies: [] };
    }
    return {};
  });
});

afterEach(() => {
  global.fetch = _originalFetch;
});


async function importPage() {
  // Import lazily so the mocks above are wired before the page module
  // sees them.
  const mod = await import("../page");
  return mod.default;
}

describe("UploadPage — Base Ontologies selector (H.8)", () => {
  it("hides the base ontologies section when the library is empty", async () => {
    mockApiGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/ontology/library")) return { data: [] };
      if (path === "/api/v1/documents") return { data: [] };
      return {};
    });

    const UploadPage = await importPage();
    render(<UploadPage />);

    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    // No selector when there's nothing to import.
    expect(screen.queryByLabelText(/Base Ontologies/i)).toBeNull();
  });

  it("renders the base ontologies multi-select with library options", async () => {
    const UploadPage = await importPage();
    render(<UploadPage />);

    const select = (await screen.findByLabelText(/Base Ontologies/i)) as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.tagName).toBe("SELECT");
    expect(select.multiple).toBe(true);

    // All three library options must be present in the BASE selector
    // (we look at this select's own <option>s rather than via screen
    // role queries because the Target selector also lists the same
    // ontology names and would produce duplicate matches).
    const baseOptionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(baseOptionLabels).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/FOAF \(16 classes, core\)/),
        expect.stringMatching(/DCMI Terms \(0 classes, core\)/),
        expect.stringMatching(/Acme Domain \(42 classes, domain\)/),
      ]),
    );
  });

  it("excludes the currently-selected target from the base options", async () => {
    const UploadPage = await importPage();
    render(<UploadPage />);

    // Wait for the library to load.
    await screen.findByLabelText(/Base Ontologies/i);

    const target = screen.getByLabelText(/Target Ontology/i) as HTMLSelectElement;
    fireEvent.change(target, { target: { value: "acme" } });

    // Acme is now the target -- it must NOT appear in the base options.
    const baseSelect = screen.getByLabelText(/Base Ontologies/i) as HTMLSelectElement;
    const baseOptionValues = Array.from(baseSelect.options).map((o) => o.value);
    expect(baseOptionValues).not.toContain("acme");
    expect(baseOptionValues).toContain("foaf");
    expect(baseOptionValues).toContain("dcterms");
  });

  it("includes base_ontology_ids in the /extraction/run POST body when bases are selected", async () => {
    const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/api/v1/extraction/run")) {
        return new Response(JSON.stringify({ run_id: "run-99" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("{}", { status: 200 });
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const UploadPage = await importPage();
    render(<UploadPage />);

    const baseSelect = (await screen.findByLabelText(/Base Ontologies/i)) as HTMLSelectElement;

    // Select foaf + dcterms.
    Array.from(baseSelect.options).forEach((opt) => {
      opt.selected = opt.value === "foaf" || opt.value === "dcterms";
    });
    fireEvent.change(baseSelect);

    // Stop the page navigation that `extractDocument` triggers on
    // success; jsdom doesn't implement window.location assignment for
    // real navigation, but the assignment still throws under strict
    // checks. Replace with a no-op.
    const locDesc = Object.getOwnPropertyDescriptor(window, "location")!;
    delete (window as { location?: Location }).location;
    (window as { location: { href: string } }).location = { href: "" };

    try {
      // Click the per-document Extract button on the recent docs list.
      const extractBtn = await screen.findByRole("button", { name: /^Extract$/i });
      fireEvent.click(extractBtn);

      await waitFor(() => {
        const runCall = fetchMock.mock.calls.find(([u]) =>
          String(u).includes("/api/v1/extraction/run"),
        );
        expect(runCall).toBeDefined();
        const body = JSON.parse(String(runCall![1]?.body));
        expect(body.document_id).toBe("doc-1");
        expect(body.base_ontology_ids).toEqual(["foaf", "dcterms"]);
      });
    } finally {
      Object.defineProperty(window, "location", locDesc);
    }
  });

  it("omits base_ontology_ids from the POST body when none are selected", async () => {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.includes("/api/v1/extraction/run")) {
        return new Response(JSON.stringify({ run_id: "run-100" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("{}", { status: 200 });
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const UploadPage = await importPage();
    render(<UploadPage />);

    await screen.findByLabelText(/Base Ontologies/i);

    const locDesc = Object.getOwnPropertyDescriptor(window, "location")!;
    delete (window as { location?: Location }).location;
    (window as { location: { href: string } }).location = { href: "" };

    try {
      const extractBtn = await screen.findByRole("button", { name: /^Extract$/i });
      fireEvent.click(extractBtn);

      await waitFor(() => {
        const runCall = fetchMock.mock.calls.find(([u]) =>
          String(u).includes("/api/v1/extraction/run"),
        );
        expect(runCall).toBeDefined();
        const body = JSON.parse(String(runCall![1]?.body));
        // Omitted entirely when there's nothing to send; the backend
        // treats absent as no bases, which is correct.
        expect(body.base_ontology_ids).toBeUndefined();
      });
    } finally {
      Object.defineProperty(window, "location", locDesc);
    }
  });
});
