/**
 * Tests for ``RelationalExtractionOverlay`` (relational/SQL schema extraction).
 *
 * Mock fidelity (per ``mock-fidelity.mdc``): the mocked ``ApiError`` mirrors
 * the real ``ApiError(status: number, body: ApiErrorBody)`` signature so a
 * future change to the real class breaks this test at compile time instead of
 * silently passing.
 *
 * Coverage targets:
 *  - Step 1 (connect): renders source-type picker + URL, validates required
 *    fields, surfaces API errors inline, transitions to preview on success.
 *  - Step 2 (preview): renders tables + FKs + summary, imports toggle
 *    propagates to the commit POST body, Back returns to step 1 preserving
 *    connection, "Extract & Import" disabled when no tables.
 *  - Step 3 (result): renders run id + ontology id, ``onImported`` fires once.
 *  - Esc + × close.
 *  - Pure helpers (``summarizeRelationalExtraction``, ``validateRelationalConnection``).
 */

import { render, screen, fireEvent, within } from "@testing-library/react";

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

import RelationalExtractionOverlay, {
  summarizeRelationalExtraction,
  validateRelationalConnection,
  SOURCE_TYPES,
} from "../RelationalExtractionOverlay";
import { api, ApiError } from "@/lib/api-client";

const mockedGet = api.get as jest.Mock;
const mockedPost = api.post as jest.Mock;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PREVIEW_RESPONSE = {
  source_type: "postgresql",
  schema_name: "public",
  db_label: "shop",
  server_version: "16.1",
  dialect: "postgresql",
  tables: [
    {
      name: "users",
      is_view: false,
      comment: "people",
      column_count: 3,
      primary_key: ["id"],
      columns: [],
      foreign_keys: [],
    },
    {
      name: "orders",
      is_view: false,
      comment: null,
      column_count: 3,
      primary_key: ["id"],
      columns: [],
      foreign_keys: [
        { columns: ["user_id"], foreign_table: "users", foreign_columns: ["id"] },
      ],
    },
    {
      name: "active_reviews",
      is_view: true,
      comment: null,
      column_count: 1,
      primary_key: ["id"],
      columns: [],
      foreign_keys: [],
    },
  ],
  table_count: 3,
  view_count: 1,
  foreign_key_count: 1,
};

const EXTRACT_RESPONSE = {
  run_id: "run_abc123",
  status: "completed",
  ontology_id: "relschema_shop_abc123",
  import_stats: { classes: 3, properties: 7, edges: 1 },
  provenance: { mode: "relational" },
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
    if (url === "/api/v1/ontology/schema/relational/tables") {
      return Promise.resolve(PREVIEW_RESPONSE);
    }
    if (url === "/api/v1/ontology/schema/relational/extract") {
      return Promise.resolve(EXTRACT_RESPONSE);
    }
    return Promise.reject(new Error(`unexpected POST ${url}`));
  });
}

/** Drive the overlay from "just rendered" to "preview step with tables". */
async function advanceToPreview(onClose = jest.fn(), onImported = jest.fn()) {
  render(<RelationalExtractionOverlay onClose={onClose} onImported={onImported} />);
  fireEvent.change(screen.getByLabelText(/Connection string/i), {
    target: { value: "postgresql://x/shop" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Connect & Preview/i }));
  await screen.findByTestId("relational-extraction-preview-step");
  return { onClose, onImported };
}

// ---------------------------------------------------------------------------
// Pure helper tests
// ---------------------------------------------------------------------------

describe("validateRelationalConnection", () => {
  const base = {
    source_type: "postgresql",
    url: "postgresql://x/shop",
    schema_name: "public",
    db_label: "",
    ontology_label: "",
  };

  it("returns null for a valid config", () => {
    expect(validateRelationalConnection(base)).toBeNull();
  });

  it("rejects an empty url", () => {
    expect(validateRelationalConnection({ ...base, url: "  " })).toMatch(
      /Connection string/,
    );
  });

  it("rejects an unsupported source type", () => {
    expect(validateRelationalConnection({ ...base, source_type: "mongo" })).toMatch(
      /Unsupported source type/,
    );
  });

  it("accepts every advertised source type", () => {
    for (const s of SOURCE_TYPES) {
      expect(validateRelationalConnection({ ...base, source_type: s.id })).toBeNull();
    }
  });
});

describe("summarizeRelationalExtraction", () => {
  it("maps tables→classes, columns→datatype props, FKs→object props", () => {
    const summary = summarizeRelationalExtraction(PREVIEW_RESPONSE);
    expect(summary.classes).toBe(3);
    expect(summary.datatypeProperties).toBe(7); // 3 + 3 + 1
    expect(summary.objectProperties).toBe(1);
  });

  it("returns zeroes for an empty preview", () => {
    const summary = summarizeRelationalExtraction({
      ...PREVIEW_RESPONSE,
      tables: [],
      table_count: 0,
      foreign_key_count: 0,
    });
    expect(summary.classes).toBe(0);
    expect(summary.datatypeProperties).toBe(0);
    expect(summary.objectProperties).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Render tests
// ---------------------------------------------------------------------------

describe("RelationalExtractionOverlay", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupHappyPath();
  });

  // -- Step 1: connect ----------------------------------------------------

  it("renders the connect step with postgresql selected by default", () => {
    render(<RelationalExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    expect(screen.getByTestId("relational-extraction-connect-step")).toBeInTheDocument();
    expect(screen.getByLabelText(/Source type/i)).toHaveValue("postgresql");
  });

  it("blocks preview when the connection string is empty", () => {
    render(<RelationalExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Connect & Preview/i }));
    expect(screen.getByTestId("relational-extraction-connect-error")).toHaveTextContent(
      /Connection string/,
    );
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces a 501 (library not installed) inline and stays on connect", async () => {
    mockedPost.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/schema/relational/tables") {
        return Promise.reject(
          new ApiError(501, {
            code: "NOT_IMPLEMENTED",
            message: "relational-schema-analyzer is not installed",
          }),
        );
      }
      return Promise.reject(new Error(`unexpected POST ${url}`));
    });

    render(<RelationalExtractionOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    fireEvent.change(screen.getByLabelText(/Connection string/i), {
      target: { value: "postgresql://x/shop" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Connect & Preview/i }));

    const err = await screen.findByTestId("relational-extraction-connect-error");
    expect(err).toHaveTextContent("relational-schema-analyzer is not installed");
    expect(screen.getByTestId("relational-extraction-connect-step")).toBeInTheDocument();
  });

  it("Esc fires onClose", () => {
    const onClose = jest.fn();
    render(<RelationalExtractionOverlay onClose={onClose} onImported={jest.fn()} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("× button fires onClose", () => {
    const onClose = jest.fn();
    render(<RelationalExtractionOverlay onClose={onClose} onImported={jest.fn()} />);
    fireEvent.click(screen.getByLabelText(/Close relational extraction/));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // -- Step 2: preview ----------------------------------------------------

  it("transitions to the preview step and renders tables", async () => {
    await advanceToPreview();
    expect(screen.getByTestId("relational-extraction-table-users")).toBeInTheDocument();
    expect(screen.getByTestId("relational-extraction-table-orders")).toBeInTheDocument();
    expect(screen.getByTestId("relational-extraction-table-active_reviews")).toBeInTheDocument();
    expect(mockedPost).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/relational/tables",
      expect.objectContaining({ source_type: "postgresql", url: "postgresql://x/shop" }),
    );
  });

  it("renders the summary line with classes + datatype + object properties", async () => {
    await advanceToPreview();
    const summary = screen.getByTestId("relational-extraction-preview-summary");
    expect(summary.textContent).toMatch(/3\s+classes/);
    expect(summary.textContent).toMatch(/7\s+datatype/);
    expect(summary.textContent).toMatch(/1\s+object properties/);
  });

  it("Back returns to the connect step and preserves the typed url", async () => {
    await advanceToPreview();
    fireEvent.click(screen.getByRole("button", { name: /Back/i }));
    expect(screen.getByTestId("relational-extraction-connect-step")).toBeInTheDocument();
    expect(screen.getByLabelText(/Connection string/i)).toHaveValue("postgresql://x/shop");
  });

  // -- Step 2 → 3: extract -----------------------------------------------

  it("Extract & Import posts the right body and transitions to the result step", async () => {
    const { onImported } = await advanceToPreview();
    await screen.findByTestId("relational-extraction-import-foaf");

    fireEvent.click(
      within(screen.getByTestId("relational-extraction-import-foaf")).getByRole("checkbox"),
    );
    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));

    await screen.findByTestId("relational-extraction-result-step");

    expect(mockedPost).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/relational/extract",
      expect.objectContaining({
        source_type: "postgresql",
        url: "postgresql://x/shop",
        extract_constraints: true,
        imports: ["foaf"],
      }),
    );
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(onImported).toHaveBeenCalledWith("relschema_shop_abc123");
  });

  it("surfaces a failed extract inline on the preview step", async () => {
    mockedPost.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/schema/relational/tables") {
        return Promise.resolve(PREVIEW_RESPONSE);
      }
      if (url === "/api/v1/ontology/schema/relational/extract") {
        return Promise.reject(
          new ApiError(502, { code: "UPSTREAM_ERROR", message: "driver crashed" }),
        );
      }
      return Promise.reject(new Error(`unexpected POST ${url}`));
    });

    await advanceToPreview();
    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));

    const err = await screen.findByTestId("relational-extraction-preview-error");
    expect(err).toHaveTextContent("driver crashed");
    expect(screen.getByTestId("relational-extraction-preview-step")).toBeInTheDocument();
    expect(screen.queryByTestId("relational-extraction-result-step")).not.toBeInTheDocument();
  });

  // -- Step 3: result ----------------------------------------------------

  it("renders the run id and ontology id on the result step", async () => {
    await advanceToPreview();
    fireEvent.click(screen.getByRole("button", { name: /Extract & Import/i }));
    await screen.findByTestId("relational-extraction-result-step");

    expect(screen.getByText(/relschema_shop_abc123/)).toBeInTheDocument();
    expect(screen.getByText(/run_abc123/)).toBeInTheDocument();
    expect(screen.getByText(/3 class\(es\)/)).toBeInTheDocument();
  });
});
