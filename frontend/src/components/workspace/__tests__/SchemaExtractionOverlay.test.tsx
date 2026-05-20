/**
 * Tests for the Stream 5 PR 2 ``SchemaExtractionOverlay``.
 *
 * Mock fidelity (per ``mock-fidelity.mdc``): the mocked ``ApiError`` mirrors
 * the real ``ApiError(status: number, body: ApiErrorBody)`` signature so a
 * future change to the real class breaks this test at compile time
 * instead of silently passing.
 *
 * Coverage targets:
 *  - Step 1 (connect): renders, validates required fields, surfaces API
 *    errors inline, transitions to step 2 on success.
 *  - Step 2 (preview): renders graphs + loose collections + summary,
 *    toggles propagate to the commit POST body, Back returns to step 1
 *    keeping connection state, "Extract & Import" disabled when
 *    everything is unchecked, errors stay inline.
 *  - Step 3 (result): renders run id + ontology id + stats, ``onImported``
 *    fires once with the new id.
 *  - Esc + × close.
 *  - Pure helpers (``summarizeExtraction``, ``validateConnection``).
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

jest.mock("@/lib/api-client", () => {
  class MockApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    api: {
      get: jest.fn(),
      post: jest.fn(),
    },
    ApiError: MockApiError,
  };
});

import SchemaExtractionOverlay, {
  summarizeExtraction,
  validateConnection,
} from "../SchemaExtractionOverlay";
import { api, ApiError } from "@/lib/api-client";

const mockedGet = api.get as jest.Mock;
const mockedPost = api.post as jest.Mock;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const GRAPHS_RESPONSE = {
  target_host: "http://localhost:8530",
  target_db: "social",
  graphs: [
    {
      name: "social_graph",
      edge_definitions: [
        {
          edge_collection: "follows",
          from_vertex_collections: ["users"],
          to_vertex_collections: ["users"],
        },
        {
          edge_collection: "authored",
          from_vertex_collections: ["users"],
          to_vertex_collections: ["posts"],
        },
      ],
      vertex_collections: ["users", "posts"],
      orphan_collections: [],
    },
    {
      name: "analytics_graph",
      edge_definitions: [
        {
          edge_collection: "viewed",
          from_vertex_collections: ["users"],
          to_vertex_collections: ["posts"],
        },
      ],
      vertex_collections: ["users", "posts"],
      orphan_collections: ["sessions"],
    },
  ],
  loose_collections: [
    { name: "logs", type: "document", count: 12345 },
    { name: "audit_edges", type: "edge", count: 42 },
  ],
};

const EXTRACT_RESPONSE = {
  run_id: "run_abc123",
  status: "completed",
  ontology_id: "schema_social_abc123",
  import_stats: { classes: 3, properties: 5, edges: 3 },
  provenance: { mode: "direct" },
  provenance_stamped: 3,
};

const REGISTRY_RESPONSE = {
  data: [
    { _key: "foaf", name: "FOAF" },
    { _key: "dcterms_minimal", name: "DCMI Terms (minimal)" },
  ],
};

function setupHappyPath() {
  mockedGet.mockImplementation((url: string) => {
    if (url.startsWith("/api/v1/ontology/library")) {
      return Promise.resolve(REGISTRY_RESPONSE);
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  mockedPost.mockImplementation((url: string) => {
    if (url === "/api/v1/ontology/schema/graphs") {
      return Promise.resolve(GRAPHS_RESPONSE);
    }
    if (url === "/api/v1/ontology/schema/extract") {
      return Promise.resolve(EXTRACT_RESPONSE);
    }
    return Promise.reject(new Error(`unexpected POST ${url}`));
  });
}

/** Drive the overlay from "just rendered" to "preview step with graphs". */
async function advanceToPreview(onClose = jest.fn(), onImported = jest.fn()) {
  render(<SchemaExtractionOverlay onClose={onClose} onImported={onImported} />);
  fireEvent.change(screen.getByLabelText(/^Database$/), {
    target: { value: "social" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Connect & Discover/i }));
  await screen.findByTestId("schema-extraction-preview-step");
  return { onClose, onImported };
}

// ---------------------------------------------------------------------------
// Pure helper tests -- pin the summary math without rendering.
// ---------------------------------------------------------------------------

describe("validateConnection", () => {
  const base = {
    target_host: "http://localhost:8530",
    target_db: "social",
    target_user: "root",
    target_password: "",
    verify_tls: true,
    ontology_label: "",
    ontology_id: "",
  };

  it("returns null for a valid config", () => {
    expect(validateConnection(base)).toBeNull();
  });

  it("rejects empty host", () => {
    expect(validateConnection({ ...base, target_host: "  " })).toMatch(/Host is required/);
  });

  it("rejects host without scheme", () => {
    expect(validateConnection({ ...base, target_host: "localhost:8530" })).toMatch(
      /not a valid URL|http/,
    );
  });

  it("rejects non-http scheme", () => {
    expect(validateConnection({ ...base, target_host: "ftp://x" })).toMatch(/http/);
  });

  it("rejects empty database", () => {
    expect(validateConnection({ ...base, target_db: "" })).toMatch(/Database name is required/);
  });

  it("rejects empty username", () => {
    expect(validateConnection({ ...base, target_user: "" })).toMatch(/Username is required/);
  });
});

describe("summarizeExtraction", () => {
  it("counts unique classes + object properties across selected graphs", () => {
    const summary = summarizeExtraction(
      GRAPHS_RESPONSE,
      new Set(["social_graph", "analytics_graph"]),
      false,
    );
    // users + posts + sessions = 3 unique classes
    expect(summary.classes).toBe(3);
    // follows + authored + viewed = 3 unique object properties
    expect(summary.objectProperties).toBe(3);
    expect(summary.sampledCollections).toBe(3);
  });

  it("excludes graphs that are unchecked", () => {
    const summary = summarizeExtraction(
      GRAPHS_RESPONSE,
      new Set(["social_graph"]),
      false,
    );
    // social_graph contributes users + posts only
    expect(summary.classes).toBe(2);
    expect(summary.objectProperties).toBe(2);
  });

  it("includes loose document/edge collections when includeLoose=true", () => {
    const summary = summarizeExtraction(
      GRAPHS_RESPONSE,
      new Set(["social_graph", "analytics_graph"]),
      true,
    );
    expect(summary.classes).toBe(4); // + logs
    expect(summary.objectProperties).toBe(4); // + audit_edges
  });

  it("excludes loose collections when includeLoose=false", () => {
    const summary = summarizeExtraction(
      GRAPHS_RESPONSE,
      new Set(["social_graph", "analytics_graph"]),
      false,
    );
    expect(summary.classes).toBe(3);
    expect(summary.objectProperties).toBe(3);
  });

  it("returns zeroes when no graphs are selected and loose is off", () => {
    const summary = summarizeExtraction(GRAPHS_RESPONSE, new Set(), false);
    expect(summary.classes).toBe(0);
    expect(summary.objectProperties).toBe(0);
    expect(summary.sampledCollections).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Render tests
// ---------------------------------------------------------------------------

describe("SchemaExtractionOverlay", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupHappyPath();
  });

  // -- Step 1: connect ----------------------------------------------------

  it("renders the connect step with default host pre-filled", () => {
    render(<SchemaExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    expect(screen.getByTestId("schema-extraction-connect-step")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Host$/)).toHaveValue("http://localhost:8530");
    expect(screen.getByLabelText(/^Database$/)).toHaveValue("");
    expect(screen.getByLabelText(/^Username$/)).toHaveValue("root");
  });

  it("blocks discover when the database field is empty", () => {
    render(<SchemaExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Connect & Discover/i }));

    const err = screen.getByTestId("schema-extraction-connect-error");
    expect(err).toHaveTextContent(/Database name is required/);
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces a 502 from the backend inline and stays on the connect step", async () => {
    mockedPost.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/schema/graphs") {
        return Promise.reject(
          new ApiError(502, { code: "UPSTREAM_ERROR", message: "auth failed" }),
        );
      }
      return Promise.reject(new Error(`unexpected POST ${url}`));
    });

    render(<SchemaExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    fireEvent.change(screen.getByLabelText(/^Database$/), { target: { value: "social" } });
    fireEvent.click(screen.getByRole("button", { name: /Connect & Discover/i }));

    const err = await screen.findByTestId("schema-extraction-connect-error");
    expect(err).toHaveTextContent("auth failed");
    expect(screen.getByTestId("schema-extraction-connect-step")).toBeInTheDocument();
    expect(screen.queryByTestId("schema-extraction-preview-step")).not.toBeInTheDocument();
  });

  it("Esc fires onClose at any step", () => {
    const onClose = jest.fn();
    render(<SchemaExtractionOverlay onClose={onClose} onImported={jest.fn()} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("× button fires onClose", () => {
    const onClose = jest.fn();
    render(<SchemaExtractionOverlay onClose={onClose} onImported={jest.fn()} />);

    fireEvent.click(screen.getByLabelText(/Close schema extraction/));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // -- Step 2: preview ----------------------------------------------------

  it("transitions to the preview step on a successful discover", async () => {
    await advanceToPreview();

    expect(screen.getByTestId("schema-extraction-preview-step")).toBeInTheDocument();
    // Both graphs should render.
    expect(screen.getByTestId("schema-extraction-graph-social_graph")).toBeInTheDocument();
    expect(screen.getByTestId("schema-extraction-graph-analytics_graph")).toBeInTheDocument();
    // Posts the right body to /schema/graphs.
    expect(mockedPost).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/graphs",
      expect.objectContaining({ target_db: "social", target_host: "http://localhost:8530" }),
    );
  });

  it("renders the summary line with classes + object properties + sampled collections", async () => {
    await advanceToPreview();

    const summary = screen.getByTestId("schema-extraction-preview-summary");
    // Default: both graphs selected + loose on:
    //   classes = users + posts + sessions + logs = 4
    //   OPs     = follows + authored + viewed + audit_edges = 4
    //   sampled = all four are doc collections (logs is a loose doc) = 4
    expect(summary.textContent).toMatch(/4\s+classes/);
    expect(summary.textContent).toMatch(/4\s+object properties/);
    expect(summary.textContent).toMatch(/4\s+document collection/);
  });

  it("toggling a graph off updates the summary", async () => {
    await advanceToPreview();

    const summaryBefore = screen.getByTestId("schema-extraction-preview-summary").textContent;
    expect(summaryBefore).toMatch(/4\s+classes/);

    const socialRow = screen.getByTestId("schema-extraction-graph-social_graph");
    const checkbox = within(socialRow).getByRole("checkbox");
    fireEvent.click(checkbox);

    await waitFor(() => {
      const summary = screen.getByTestId("schema-extraction-preview-summary").textContent;
      // After unchecking social_graph: analytics_graph contributes users + posts +
      // sessions = 3 classes (still), and loose adds logs → 4 classes. So this
      // tests the "graph is unchecked but vertices remain in_graph_cols" branch
      // of the summarize helper too. Actually since vertices stay tracked for
      // double-counting prevention, we still get users + posts + sessions + logs
      // = 4 from the merge with loose. Let's assert the OPs count instead which
      // does change clearly: only viewed + audit_edges remain → 2.
      expect(summary).toMatch(/2\s+object properties/);
    });
  });

  it("disables Extract & Import when everything is unchecked", async () => {
    await advanceToPreview();

    // Uncheck both graphs.
    fireEvent.click(
      within(screen.getByTestId("schema-extraction-graph-social_graph")).getByRole("checkbox"),
    );
    fireEvent.click(
      within(screen.getByTestId("schema-extraction-graph-analytics_graph")).getByRole("checkbox"),
    );
    // Uncheck loose.
    fireEvent.click(screen.getByLabelText(/Include loose collections/));

    const extractBtn = screen.getByRole("button", { name: /Extract & Import/i });
    expect(extractBtn).toBeDisabled();
  });

  it("Back returns to the connect step and preserves the typed db name", async () => {
    await advanceToPreview();

    fireEvent.click(screen.getByRole("button", { name: /Back/i }));

    expect(screen.getByTestId("schema-extraction-connect-step")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Database$/)).toHaveValue("social");
  });

  // -- Step 2 → 3: extract -----------------------------------------------

  it("Extract & Import posts the right body and transitions to the result step", async () => {
    const { onImported } = await advanceToPreview();
    // Wait for the registry fetch to settle so the imports section renders.
    await screen.findByTestId("schema-extraction-import-foaf");

    // Pick one import.
    fireEvent.click(
      within(screen.getByTestId("schema-extraction-import-foaf")).getByRole("checkbox"),
    );

    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));

    await screen.findByTestId("schema-extraction-result-step");

    expect(mockedPost).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/extract",
      expect.objectContaining({
        target_db: "social",
        // Both graphs selected by default → graph_names normalises to null.
        graph_names: null,
        include_loose: true,
        sample_fields: true,
        field_sample_limit: 10,
        imports: ["foaf"],
      }),
    );
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(onImported).toHaveBeenCalledWith("schema_social_abc123");
  });

  it("passes a partial graph_names array when not all graphs are selected", async () => {
    await advanceToPreview();
    // Uncheck analytics_graph so only social_graph remains.
    fireEvent.click(
      within(screen.getByTestId("schema-extraction-graph-analytics_graph")).getByRole("checkbox"),
    );

    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));

    await screen.findByTestId("schema-extraction-result-step");

    expect(mockedPost).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/extract",
      expect.objectContaining({
        graph_names: ["social_graph"],
      }),
    );
  });

  it("surfaces a failed extract inline on the preview step", async () => {
    mockedPost.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/schema/graphs") {
        return Promise.resolve(GRAPHS_RESPONSE);
      }
      if (url === "/api/v1/ontology/schema/extract") {
        return Promise.reject(
          new ApiError(500, { code: "INTERNAL_ERROR", message: "import crashed" }),
        );
      }
      return Promise.reject(new Error(`unexpected POST ${url}`));
    });

    await advanceToPreview();
    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));

    const err = await screen.findByTestId("schema-extraction-preview-error");
    expect(err).toHaveTextContent("import crashed");
    expect(screen.getByTestId("schema-extraction-preview-step")).toBeInTheDocument();
    expect(screen.queryByTestId("schema-extraction-result-step")).not.toBeInTheDocument();
  });

  // -- Step 3: result ----------------------------------------------------

  it("renders the run id and ontology id on the result step", async () => {
    await advanceToPreview();
    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));
    await screen.findByTestId("schema-extraction-result-step");

    expect(screen.getByText(/schema_social_abc123/)).toBeInTheDocument();
    expect(screen.getByText(/run_abc123/)).toBeInTheDocument();
    expect(screen.getByText(/3 class\(es\)/)).toBeInTheDocument();
  });
});
