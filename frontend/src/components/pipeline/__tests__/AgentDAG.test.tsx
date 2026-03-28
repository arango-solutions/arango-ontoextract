import { render, screen } from "@testing-library/react";
import type { StepStatus, StepStatusValue } from "@/types/pipeline";
import { PIPELINE_STEPS } from "@/types/pipeline";

jest.mock("reactflow", () => {
  const Original = jest.requireActual("reactflow");
  return {
    __esModule: true,
    ...Original,
    default: function MockReactFlow({
      nodes,
    }: {
      nodes: Array<{
        id: string;
        data: { label: string; stepStatus: { status: string }; stepKey: string };
        type: string;
      }>;
    }) {
      const AgentNode = Original.default ? null : null;
      void AgentNode;
      return (
        <div data-testid="mock-reactflow">
          {nodes.map((node) => (
            <div key={node.id} data-testid={`dag-node-${node.id}`}>
              <span>{node.data.label}</span>
              <span data-testid={`status-${node.id}`}>
                {node.data.stepStatus.status}
              </span>
            </div>
          ))}
        </div>
      );
    },
    Position: Original.Position,
    Handle: function MockHandle() {
      return null;
    },
    Background: function MockBackground() {
      return null;
    },
    BackgroundVariant: Original.BackgroundVariant ?? { Dots: "dots" },
  };
});

// Must import after mock
// eslint-disable-next-line @typescript-eslint/no-require-imports
const AgentDAGModule = require("@/components/pipeline/AgentDAG");
const AgentDAG = AgentDAGModule.default;

function buildSteps(
  overrides: Partial<Record<string, StepStatusValue>> = {},
): Map<string, StepStatus> {
  const map = new Map<string, StepStatus>();
  for (const step of PIPELINE_STEPS) {
    map.set(step, { status: overrides[step] ?? "pending" });
  }
  return map;
}

describe("AgentDAG", () => {
  it("renders all 5 pipeline nodes", () => {
    const steps = buildSteps();
    render(<AgentDAG steps={steps} />);

    for (const step of PIPELINE_STEPS) {
      expect(screen.getByTestId(`dag-node-${step}`)).toBeInTheDocument();
    }
  });

  it("renders correct labels for each node", () => {
    const steps = buildSteps();
    render(<AgentDAG steps={steps} />);

    expect(screen.getByText("Strategy Selector")).toBeInTheDocument();
    expect(screen.getByText("Extraction Agent")).toBeInTheDocument();
    expect(screen.getByText("Consistency Checker")).toBeInTheDocument();
    expect(screen.getByText("Entity Resolution Agent")).toBeInTheDocument();
    expect(screen.getByText("Pre-Curation Filter")).toBeInTheDocument();
  });

  it("shows pending status for all nodes initially", () => {
    const steps = buildSteps();
    render(<AgentDAG steps={steps} />);

    for (const step of PIPELINE_STEPS) {
      expect(screen.getByTestId(`status-${step}`)).toHaveTextContent(
        "pending",
      );
    }
  });

  it("reflects running status on a node", () => {
    const steps = buildSteps({ strategy_selector: "running" });
    render(<AgentDAG steps={steps} />);

    expect(
      screen.getByTestId("status-strategy_selector"),
    ).toHaveTextContent("running");
  });

  it("reflects completed status", () => {
    const steps = buildSteps({
      strategy_selector: "completed",
      extraction_agent: "completed",
      consistency_checker: "running",
    });
    render(<AgentDAG steps={steps} />);

    expect(
      screen.getByTestId("status-strategy_selector"),
    ).toHaveTextContent("completed");
    expect(
      screen.getByTestId("status-extraction_agent"),
    ).toHaveTextContent("completed");
    expect(
      screen.getByTestId("status-consistency_checker"),
    ).toHaveTextContent("running");
  });

  it("reflects failed status", () => {
    const steps = buildSteps({
      strategy_selector: "completed",
      extraction_agent: "failed",
    });
    render(<AgentDAG steps={steps} />);

    expect(
      screen.getByTestId("status-extraction_agent"),
    ).toHaveTextContent("failed");
  });
});
