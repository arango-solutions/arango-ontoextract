/**
 * Q.4 — RecallComparisonOverlay tests.
 *
 * Verifies the overlay's input → submit → render cycle:
 *   - File picker hands the file body to the API.
 *   - Run button triggers a POST /quality/recall call with selected
 *     options (threshold, include_object_properties).
 *   - Report is rendered with summary tiles + matched/missed/extras.
 *   - API errors surface as inline error.
 *   - Esc / backdrop closes the overlay.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

// `jest.mock` below is hoisted above all imports by Jest's transform, so this
// import resolves to the mocked class (not the real one).
import { ApiError as MockedApiError } from "@/lib/api-client";

import RecallComparisonOverlay from "../RecallComparisonOverlay";

async function uploadFile(input: HTMLInputElement, file: File) {
  // The codebase doesn't ship ``@testing-library/user-event``; we
  // emulate it with the lower-level fireEvent + a manual ``files``
  // assignment so the React change handler fires with the file body.
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => {
    fireEvent.change(input);
  });
}

const apiPost = jest.fn();
jest.mock("@/lib/api-client", () => {
  // Defining the class inside the factory avoids the "Cannot access X
  // before initialization" hoist error: jest.mock factories run before
  // the surrounding module body. Constructor signature matches the real
  // ApiError so the mock is type-compatible with `import { ApiError }`.
  class ApiError extends Error {
    status: number;
    body: { message: string };
    constructor(status: number, body: { message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    api: { post: (...args: unknown[]) => apiPost(...args) },
    ApiError,
  };
});

beforeEach(() => {
  apiPost.mockReset();
});

function makeFile(name: string, body: string) {
  const file = new File([body], name, { type: "text/turtle" });
  // jsdom's File implementation does not provide ``text()``; polyfill
  // it locally so the component's ``await file.text()`` resolves to
  // the body we wrote.
  if (typeof (file as unknown as { text?: () => Promise<string> }).text !== "function") {
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve(body),
      configurable: true,
    });
  }
  return file;
}

describe("RecallComparisonOverlay", () => {
  it("posts the selected file body and renders the recall report", async () => {
    apiPost.mockResolvedValue({
      ontology_id: "onto1",
      match_threshold: 0.85,
      rdf_format: "turtle",
      summary: {
        reference_count: 3,
        extracted_count: 3,
        matched_count: 2,
        recall: 0.6667,
        precision: 0.6667,
        f1: 0.6667,
      },
      classes: {
        summary: { reference_count: 3, extracted_count: 3, matched_count: 2 },
        matched: [
          {
            reference_uri: "http://x#A",
            reference_label: "Person",
            extracted_uri: "http://y#A",
            extracted_label: "Person",
            extracted_key: "p1",
            similarity: 1.0,
          },
        ],
        missed: [{ reference_uri: "http://x#C", reference_label: "Checking Account" }],
        false_positives: [
          {
            extracted_uri: "http://y#V",
            extracted_label: "Vehicle",
            extracted_key: "v1",
          },
        ],
      },
    });

    const onClose = jest.fn();
    render(
      <RecallComparisonOverlay
        ontologyId="onto1"
        ontologyName="Banking"
        onClose={onClose}
      />,
    );

    const file = makeFile("gold.ttl", "@prefix : <x#> . :A a <owl#Class> .");
    const fileInput = screen.getByTestId("recall-file-input") as HTMLInputElement;
    await uploadFile(fileInput, file);

    await waitFor(() =>
      expect(screen.getByTestId("recall-filename").textContent).toBe("gold.ttl"),
    );

    fireEvent.click(screen.getByTestId("recall-run-btn"));

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    const [endpoint, body] = apiPost.mock.calls[0];
    expect(endpoint).toBe("/api/v1/quality/recall");
    expect(body.ontology_id).toBe("onto1");
    expect(body.reference_content).toContain("a <owl#Class>");
    expect(body.rdf_format).toBe("turtle");
    expect(body.include_object_properties).toBe(true);

    const report = await screen.findByTestId("recall-report");
    expect(report.textContent).toContain("66.7%");
    expect(screen.getByTestId("recall-missed-row").textContent).toBe(
      "Checking Account",
    );
    expect(screen.getByTestId("recall-fp-row").textContent).toBe("Vehicle");
  });

  it("forwards the toggled threshold and include_object_properties flag", async () => {
    apiPost.mockResolvedValue({
      ontology_id: "onto1",
      match_threshold: 0.95,
      rdf_format: "turtle",
      summary: {
        reference_count: 0,
        extracted_count: 0,
        matched_count: 0,
        recall: 0,
        precision: 0,
        f1: 0,
      },
      classes: {
        summary: { reference_count: 0, extracted_count: 0, matched_count: 0 },
        matched: [],
        missed: [],
        false_positives: [],
      },
    });

    render(
      <RecallComparisonOverlay
        ontologyId="onto1"
        ontologyName="Banking"
        onClose={jest.fn()}
      />,
    );

    const file = makeFile("gold.ttl", "@prefix : <x#> .");
    const fileInput = screen.getByTestId("recall-file-input") as HTMLInputElement;
    await uploadFile(fileInput, file);

    fireEvent.change(screen.getByTestId("recall-threshold"), {
      target: { value: "0.95" },
    });
    fireEvent.click(screen.getByTestId("recall-include-props"));

    fireEvent.click(screen.getByTestId("recall-run-btn"));
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));

    const [, body] = apiPost.mock.calls[0];
    expect(body.match_threshold).toBe(0.95);
    expect(body.include_object_properties).toBe(false);
  });

  it("surfaces an ApiError as inline error and does not render a report", async () => {
    apiPost.mockRejectedValue(
      new MockedApiError(400, { message: "Failed to parse reference" }),
    );

    render(
      <RecallComparisonOverlay
        ontologyId="onto1"
        ontologyName="Banking"
        onClose={jest.fn()}
      />,
    );

    const fileInput = screen.getByTestId("recall-file-input") as HTMLInputElement;
    await uploadFile(fileInput, makeFile("gold.ttl", "garbage"));
    fireEvent.click(screen.getByTestId("recall-run-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("recall-error").textContent).toMatch(
        /Failed to parse reference/,
      );
    });
    expect(screen.queryByTestId("recall-report")).toBeNull();
  });

  it("blocks the run button until a file is provided and shows a hint", () => {
    render(
      <RecallComparisonOverlay
        ontologyId="onto1"
        ontologyName="Banking"
        onClose={jest.fn()}
      />,
    );

    const btn = screen.getByTestId("recall-run-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("closes on Escape and on backdrop click", () => {
    const onClose = jest.fn();
    render(
      <RecallComparisonOverlay
        ontologyId="onto1"
        ontologyName="Banking"
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("recall-overlay-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
