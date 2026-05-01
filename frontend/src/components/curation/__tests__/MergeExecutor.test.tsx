import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import MergeExecutor from "@/components/curation/MergeExecutor";
import type {
  MergeCandidate,
  EntityDetail,
} from "@/types/entity-resolution";

const MOCK_CANDIDATE: MergeCandidate = {
  pair_id: "pair_001",
  entity_1: { key: "cls_001", uri: "http://example.org/Person", label: "Person" },
  entity_2: { key: "cls_002", uri: "http://example.org/Individual", label: "Individual" },
  overall_score: 0.92,
  field_scores: {
    label_sim: 0.7,
    description_sim: 0.95,
    uri_sim: 0.6,
    topology_sim: 0.88,
  },
  status: "pending",
};

const MOCK_ENTITY_LEFT: EntityDetail = {
  key: "cls_001",
  uri: "http://example.org/Person",
  label: "Person",
  description: "A human being with consciousness.",
  rdf_type: "owl:Class",
  properties: {
    name: "string",
    age: "integer",
  },
  edges: [
    { type: "subclass_of", target_label: "Agent", target_key: "cls_100" },
  ],
};

const MOCK_ENTITY_RIGHT: EntityDetail = {
  key: "cls_002",
  uri: "http://example.org/Individual",
  label: "Individual",
  description: "A single person in society.",
  rdf_type: "owl:Class",
  properties: {
    name: "string",
    email: "string",
  },
  edges: [
    { type: "has_property", target_label: "birthDate", target_key: "prop_200" },
  ],
};

const MOCK_MERGE_RESULT = {
  merged_key: "cls_001",
  merged_label: "Person",
  deprecated_keys: ["cls_002"],
  edges_transferred: 1,
};

function mockFetchSuccess() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(MOCK_MERGE_RESULT),
  });
}

function mockFetchFailure() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    statusText: "Conflict",
    json: () =>
      Promise.resolve({
        error: { code: "MERGE_CONFLICT", message: "Cannot merge these entities" },
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("MergeExecutor", () => {
  it("shows loading state when entities are loading", () => {
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={null}
        entityRight={null}
        loading={true}
      />,
    );

    expect(screen.getByTestId("merge-executor-loading")).toBeInTheDocument();
  });

  it("renders side-by-side comparison of entity fields", () => {
    mockFetchSuccess();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    expect(screen.getByTestId("merge-executor")).toBeInTheDocument();
    const labelRow = screen.getByTestId("field-comparison-label");
    expect(labelRow).toBeInTheDocument();
    expect(screen.getByTestId("field-comparison-description")).toBeInTheDocument();
    expect(screen.getByTestId("field-comparison-uri")).toBeInTheDocument();

    // Entity labels appear in both the label row and the edge-list headers, so
    // scope the comparison-row assertions to the row's own subtree.
    expect(within(labelRow).getByText("Person")).toBeInTheDocument();
    expect(within(labelRow).getByText("Individual")).toBeInTheDocument();
    expect(screen.getByText("A human being with consciousness.")).toBeInTheDocument();
    expect(screen.getByText("A single person in society.")).toBeInTheDocument();
  });

  it("allows selecting right entity values", () => {
    mockFetchSuccess();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    fireEvent.click(screen.getByTestId("select-right-label"));

    fireEvent.click(screen.getByTestId("toggle-preview-btn"));

    expect(screen.getByTestId("merge-preview")).toHaveTextContent("Individual");
  });

  it("shows merge preview when toggled", () => {
    mockFetchSuccess();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    expect(screen.queryByTestId("merge-preview")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("toggle-preview-btn"));
    expect(screen.getByTestId("merge-preview")).toBeInTheDocument();
  });

  it("executes merge and shows result", async () => {
    mockFetchSuccess();
    const onMerged = jest.fn();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
        onMerged={onMerged}
      />,
    );

    fireEvent.click(screen.getByTestId("execute-merge-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("merge-executor-result")).toBeInTheDocument();
    });

    expect(screen.getByText("Merge Complete")).toBeInTheDocument();
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(onMerged).toHaveBeenCalledWith(MOCK_MERGE_RESULT);
  });

  it("shows error when merge fails", async () => {
    mockFetchFailure();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    fireEvent.click(screen.getByTestId("execute-merge-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("merge-error")).toBeInTheDocument();
    });

    expect(screen.getByText("Cannot merge these entities")).toBeInTheDocument();
  });

  it("displays edge lists for both entities", () => {
    mockFetchSuccess();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    // Edge list items render the type, an arrow, and the target label as
    // sibling text nodes; use substring matching rather than exact text.
    expect(screen.getByText(/Agent/)).toBeInTheDocument();
    expect(screen.getByText(/birthDate/)).toBeInTheDocument();
  });

  it("shows property comparison when entities have properties", () => {
    mockFetchSuccess();
    render(
      <MergeExecutor
        candidate={MOCK_CANDIDATE}
        entityLeft={MOCK_ENTITY_LEFT}
        entityRight={MOCK_ENTITY_RIGHT}
        loading={false}
      />,
    );

    expect(screen.getByText("Properties")).toBeInTheDocument();
  });
});
