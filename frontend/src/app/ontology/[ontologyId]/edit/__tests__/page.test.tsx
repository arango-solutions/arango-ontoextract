import { render, screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api-client";
import type { OntologyClass, OntologyEdge, OntologyRegistryEntry } from "@/types/curation";

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

jest.mock("next/navigation", () => ({
  useParams: () => ({ ontologyId: "onto_123" }),
}));

jest.mock("@/components/graph/GraphCanvas", () => {
  return function MockGraphCanvas(props: {
    classes: { _key: string; label: string }[];
    colorMode: string;
  }) {
    return (
      <div data-testid="graph-canvas">
        {props.classes.map((c) => (
          <div key={c._key} data-testid={`graph-node-${c._key}`}>{c.label}</div>
        ))}
        <span data-testid="color-mode">{props.colorMode}</span>
      </div>
    );
  };
});

jest.mock("@/components/timeline/VCRTimeline", () => {
  return function MockVCRTimeline() {
    return <div data-testid="vcr-timeline">VCR Timeline Component</div>;
  };
});

jest.mock("@/lib/api-client", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    del: jest.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
  getApiBaseUrl: () => "http://localhost:8001",
}));

jest.mock("@/components/curation/NodeDetail", () => {
  return function MockNodeDetail({ node }: { node: { label: string } }) {
    return <div data-testid="node-detail">{node.label}</div>;
  };
});

jest.mock("@/components/curation/ProvenancePanel", () => {
  return function MockProvenancePanel() {
    return <div data-testid="provenance-panel">Provenance</div>;
  };
});

jest.mock("@/components/timeline/EntityHistory", () => {
  return function MockEntityHistory() {
    return <div data-testid="entity-history">History</div>;
  };
});

const mockApi = api as jest.Mocked<typeof api>;

const mockClasses: OntologyClass[] = [
  {
    _key: "cls_001",
    uri: "http://example.org/ontology#Person",
    label: "Person",
    description: "A human being.",
    rdf_type: "owl:Class",
    confidence: 0.85,
    status: "pending",
    ontology_id: "onto_123",
    created: "2026-03-15T10:00:00Z",
    expired: null,
  },
  {
    _key: "cls_002",
    uri: "http://example.org/ontology#Organization",
    label: "Organization",
    description: "An organized group.",
    rdf_type: "owl:Class",
    confidence: 0.72,
    status: "approved",
    ontology_id: "onto_123",
    created: "2026-03-15T10:00:00Z",
    expired: null,
  },
];

const mockEdges: OntologyEdge[] = [
  {
    _key: "edge_001",
    _from: "ontology_classes/cls_001",
    _to: "ontology_classes/cls_002",
    type: "related_to",
    label: "related to",
  },
];

const mockRegistry: OntologyRegistryEntry = {
  _key: "onto_123",
  name: "Test Ontology",
  description: "An ontology for testing",
  tier: "domain",
  class_count: 2,
  property_count: 1,
  edge_count: 1,
  ontology_id: "onto_123",
  status: "active",
};

// Must import after mocks
const PageModule = require("../page");
const OntologyEditorPage = PageModule.default;

function setupSuccessfulApi() {
  mockApi.get.mockImplementation((path: string) => {
    if (path.includes("/classes")) {
      return Promise.resolve({ data: mockClasses });
    }
    if (path.includes("/edges")) {
      return Promise.resolve({ data: mockEdges });
    }
    if (path.includes("/properties")) {
      return Promise.resolve({ data: [] });
    }
    if (path.includes("/library")) {
      return Promise.resolve({
        data: [mockRegistry],
        cursor: null,
        has_more: false,
        total_count: 1,
      });
    }
    return Promise.reject(new Error(`Unexpected API call: ${path}`));
  });
}

describe("OntologyEditorPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockApi.get.mockReturnValue(new Promise(() => {}));
    render(<OntologyEditorPage />);
    expect(screen.getByText("Loading ontology graph...")).toBeInTheDocument();
  });

  it("renders header with Ontology Editor title", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByText("Ontology Editor")).toBeInTheDocument();
    });
  });

  it("shows ontology name from registry in header", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByText("Test Ontology")).toBeInTheDocument();
    });
  });

  it("renders Add Class button", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByTestId("add-class-btn")).toBeInTheDocument();
    });
  });

  it("renders Add Property button (disabled when no node selected)", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      const btn = screen.getByTestId("add-property-btn");
      expect(btn).toBeInTheDocument();
      expect(btn).toBeDisabled();
    });
  });

  it("renders Export dropdown button", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByTestId("export-btn")).toBeInTheDocument();
    });
  });

  it("renders Back to Library link", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      const link = screen.getByText(/Library/);
      expect(link).toBeInTheDocument();
      expect(link.closest("a")).toHaveAttribute("href", "/library");
    });
  });

  it("shows error state with retry button on API failure", async () => {
    mockApi.get.mockRejectedValue(new Error("Network error"));
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(
        screen.getByText("Failed to load ontology graph"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("shows empty state when ontology has no classes", async () => {
    mockApi.get.mockImplementation((path: string) => {
      if (path.includes("/classes")) return Promise.resolve({ data: [] });
      if (path.includes("/edges")) return Promise.resolve({ data: [] });
      if (path.includes("/properties")) return Promise.resolve({ data: [] });
      if (path.includes("/library")) {
        return Promise.resolve({
          data: [mockRegistry],
          cursor: null,
          has_more: false,
          total_count: 1,
        });
      }
      return Promise.reject(new Error(`Unexpected: ${path}`));
    });

    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(
        screen.getByText("This ontology has no classes yet"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Add First Class")).toBeInTheDocument();
    expect(screen.getByText("Back to Library")).toBeInTheDocument();
  });

  it("shows placeholder text when no node is selected", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(
        screen.getByText("Select a node or edge to view details"),
      ).toBeInTheDocument();
    });
  });

  it("calls the correct API endpoints on mount", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(mockApi.get).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_123/classes",
      );
      expect(mockApi.get).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_123/edges",
      );
      expect(mockApi.get).toHaveBeenCalledWith("/api/v1/ontology/library");
    });
  });

  it("renders color mode toggle buttons", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByText("Confidence")).toBeInTheDocument();
      expect(screen.getByText("Status")).toBeInTheDocument();
    });
  });

  it("renders VCR Timeline toggle button", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByText("VCR Timeline")).toBeInTheDocument();
    });
  });

  it("does not render Promote or Diff View buttons", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByText("Ontology Editor")).toBeInTheDocument();
    });
    expect(screen.queryByText("Promote")).not.toBeInTheDocument();
    expect(screen.queryByText("Diff View")).not.toBeInTheDocument();
  });

  it("renders graph canvas with loaded classes", async () => {
    setupSuccessfulApi();
    render(<OntologyEditorPage />);

    await waitFor(() => {
      expect(screen.getByTestId("graph-canvas")).toBeInTheDocument();
    });
    expect(screen.getByTestId("graph-node-cls_001")).toBeInTheDocument();
    expect(screen.getByTestId("graph-node-cls_002")).toBeInTheDocument();
  });
});
