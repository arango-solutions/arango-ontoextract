import { render, screen, fireEvent } from "@testing-library/react";
import OntologyCard from "@/components/library/OntologyCard";
import type { OntologyRegistryEntry } from "@/types/curation";

const mockOntology: OntologyRegistryEntry = {
  _key: "onto_001",
  name: "AWS Cloud Ontology",
  description: "Classes and properties for AWS cloud resources.",
  tier: "domain",
  class_count: 42,
  property_count: 87,
  edge_count: 120,
  last_updated: new Date(Date.now() - 3_600_000).toISOString(),
  created_at: "2026-01-01T00:00:00Z",
  ontology_id: "aws_cloud",
  status: "active",
};

describe("OntologyCard", () => {
  it("uses label when name is missing", () => {
    const onlyLabel = {
      ...mockOntology,
      name: undefined,
      label: "From RDF label",
    };
    render(<OntologyCard ontology={onlyLabel} />);
    expect(screen.getByText("From RDF label")).toBeInTheDocument();
  });

  it("renders ontology name and description", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.getByText("AWS Cloud Ontology")).toBeInTheDocument();
    expect(
      screen.getByText("Classes and properties for AWS cloud resources."),
    ).toBeInTheDocument();
  });

  it("renders tier badge", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.getByTestId("tier-badge")).toHaveTextContent("Domain");
  });

  it("displays class, property, and edge counts", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("87")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("shows active status", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("calls onClick with ontology key", () => {
    const onClick = jest.fn();
    render(<OntologyCard ontology={mockOntology} onClick={onClick} />);
    fireEvent.click(screen.getByTestId("ontology-card-onto_001"));
    expect(onClick).toHaveBeenCalledWith("onto_001");
  });

  it("renders local tier badge correctly", () => {
    const localOntology = { ...mockOntology, tier: "local" as const };
    render(<OntologyCard ontology={localOntology} />);
    expect(screen.getByTestId("tier-badge")).toHaveTextContent("Local");
  });

  it("shows relative time for last updated", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.getByText(/Updated/)).toBeInTheDocument();
  });

  it("handles missing description", () => {
    const noDesc = { ...mockOntology, description: "" };
    render(<OntologyCard ontology={noDesc} />);
    expect(
      screen.getByText("No description available."),
    ).toBeInTheDocument();
  });

  it("renders health score when present", () => {
    const withHealth = { ...mockOntology, health_score: 82 };
    render(<OntologyCard ontology={withHealth} />);
    expect(screen.getByTestId("health-score")).toBeInTheDocument();
    expect(screen.getByText("82")).toBeInTheDocument();
  });

  it("does not render health score when absent", () => {
    render(<OntologyCard ontology={mockOntology} />);
    expect(screen.queryByTestId("health-score")).not.toBeInTheDocument();
  });

  it("renders green color for high health score", () => {
    const highHealth = { ...mockOntology, health_score: 85 };
    render(<OntologyCard ontology={highHealth} />);
    const badge = screen.getByText("85");
    expect(badge.className).toContain("text-green-700");
  });

  it("renders yellow color for medium health score", () => {
    const medHealth = { ...mockOntology, health_score: 55 };
    render(<OntologyCard ontology={medHealth} />);
    const badge = screen.getByText("55");
    expect(badge.className).toContain("text-yellow-700");
  });

  it("renders red color for low health score", () => {
    const lowHealth = { ...mockOntology, health_score: 30 };
    render(<OntologyCard ontology={lowHealth} />);
    const badge = screen.getByText("30");
    expect(badge.className).toContain("text-red-700");
  });
});
