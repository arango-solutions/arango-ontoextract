import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import NodeActions from "@/components/curation/NodeActions";

function mockFetchSuccess() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ status: "ok" }),
  });
}

function mockFetchFailure() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    statusText: "Bad Request",
    json: () =>
      Promise.resolve({
        error: { code: "VALIDATION_ERROR", message: "Invalid decision" },
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("NodeActions", () => {
  it("renders all four action buttons", () => {
    mockFetchSuccess();
    render(
      <NodeActions
        entityKey="cls_001"
        entityType="class"
        runId="run_abc"
        currentStatus="pending"
      />,
    );

    expect(screen.getByTestId("approve-btn")).toBeInTheDocument();
    expect(screen.getByTestId("reject-btn")).toBeInTheDocument();
    expect(screen.getByTestId("edit-btn")).toBeInTheDocument();
    expect(screen.getByTestId("merge-btn")).toBeInTheDocument();
  });

  it("calls onDecision optimistically on approve", async () => {
    mockFetchSuccess();
    const onDecision = jest.fn();
    render(
      <NodeActions
        entityKey="cls_001"
        entityType="class"
        runId="run_abc"
        currentStatus="pending"
        onDecision={onDecision}
      />,
    );

    fireEvent.click(screen.getByTestId("approve-btn"));
    expect(onDecision).toHaveBeenCalledWith("cls_001", "approve");

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
  });

  it("calls API with correct payload on reject (including Q.5 latency)", async () => {
    mockFetchSuccess();
    render(
      <NodeActions
        entityKey="cls_001"
        entityType="class"
        runId="run_abc"
        currentStatus="pending"
      />,
    );

    fireEvent.click(screen.getByTestId("reject-btn"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/curation/decide"),
        expect.objectContaining({ method: "POST" }),
      );
    });

    const callArgs = (global.fetch as jest.Mock).mock.calls[0];
    const body = JSON.parse(callArgs[1].body);
    expect(body).toEqual(
      expect.objectContaining({
        run_id: "run_abc",
        entity_key: "cls_001",
        entity_type: "class",
        decision: "reject",
      }),
    );
    // Q.5: every decide call carries a non-negative latency so the
    // backend can compute concepts/hour.
    expect(typeof body.decision_latency_ms).toBe("number");
    expect(body.decision_latency_ms).toBeGreaterThanOrEqual(0);
  });

  it("shows error when API call fails", async () => {
    mockFetchFailure();
    render(
      <NodeActions
        entityKey="cls_001"
        entityType="class"
        runId="run_abc"
        currentStatus="pending"
      />,
    );

    fireEvent.click(screen.getByTestId("approve-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("action-error")).toBeInTheDocument();
    });
  });

  it("disables buttons while loading", async () => {
    global.fetch = jest.fn().mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () =>
              resolve({
                ok: true,
                json: () => Promise.resolve({ status: "ok" }),
              }),
            100,
          ),
        ),
    );

    render(
      <NodeActions
        entityKey="cls_001"
        entityType="class"
        runId="run_abc"
        currentStatus="pending"
      />,
    );

    fireEvent.click(screen.getByTestId("approve-btn"));

    expect(screen.getByTestId("approve-btn")).toBeDisabled();
    expect(screen.getByTestId("reject-btn")).toBeDisabled();

    await waitFor(() => {
      expect(screen.getByTestId("approve-btn")).not.toBeDisabled();
    });
  });
});
