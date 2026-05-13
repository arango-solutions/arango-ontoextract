import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import VCRTimeline from "@/components/timeline/VCRTimeline";
import type { TimelineEvent } from "@/types/timeline";

const mockEvents: TimelineEvent[] = [
  {
    timestamp: "2026-03-10T10:00:00Z",
    event_type: "created",
    entity_key: "cls_001",
    entity_label: "Person",
    collection: "ontology_classes",
  },
  {
    timestamp: "2026-03-12T14:00:00Z",
    event_type: "edited",
    entity_key: "cls_001",
    entity_label: "Person",
    collection: "ontology_classes",
  },
  {
    timestamp: "2026-03-15T09:00:00Z",
    event_type: "approved",
    entity_key: "cls_002",
    entity_label: "Organization",
    collection: "ontology_classes",
  },
];

function mockFetchEvents(events: TimelineEvent[]) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: events }),
  });
}

function mockFetchEmpty() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: [] }),
  });
}

function mockFetchError() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    statusText: "Not Found",
    json: () =>
      Promise.resolve({
        error: { code: "NOT_FOUND", message: "Timeline not found" },
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("VCRTimeline", () => {
  it("renders timeline controls after loading", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("vcr-timeline")).toBeInTheDocument();
    });

    expect(screen.getByTestId("timeline-play-pause")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-rewind")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-ff")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-slider")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-speed")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    global.fetch = jest.fn().mockImplementation(
      () => new Promise(() => {}),
    );
    render(<VCRTimeline ontologyId="onto_abc" />);
    expect(screen.getByTestId("timeline-loading")).toBeInTheDocument();
  });

  it("shows empty state when no events", async () => {
    mockFetchEmpty();
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
    });
  });

  it("shows error state on API failure", async () => {
    mockFetchError();
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-error")).toBeInTheDocument();
    });
  });

  it("displays current event info", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByText("Organization")).toBeInTheDocument();
    });

    expect(screen.getByText("3 / 3")).toBeInTheDocument();
  });

  it("navigates with rewind button", async () => {
    mockFetchEvents(mockEvents);
    const onTimestamp = jest.fn();
    render(
      <VCRTimeline ontologyId="onto_abc" onTimestampChange={onTimestamp} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("vcr-timeline")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("timeline-rewind"));

    await waitFor(() => {
      expect(screen.getByText("2 / 3")).toBeInTheDocument();
    });
  });

  it("slider changes current position", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-slider")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("timeline-slider"), {
      target: { value: "0" },
    });

    await waitFor(() => {
      expect(screen.getByText("1 / 3")).toBeInTheDocument();
    });
  });

  it("cycles speed on speed button click", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-speed")).toBeInTheDocument();
    });

    expect(screen.getByTestId("timeline-speed")).toHaveTextContent("1x");
    fireEvent.click(screen.getByTestId("timeline-speed"));
    expect(screen.getByTestId("timeline-speed")).toHaveTextContent("2x");
  });

  it("starts at the LATEST event on initial load (not the first)", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("vcr-timeline")).toBeInTheDocument();
    });

    // Latest event in mockEvents (sorted ascending by timestamp) is
    // "Organization" at index 2 -- the slider must land at 3 / 3, not
    // 1 / 3, so the canvas renders the COMPLETED ontology rather than
    // a partial historical snapshot.
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("snaps to LATEST when parent switches ontology (regression)", async () => {
    // First ontology: 3 events -- start at index 2 (3 / 3).
    // Second ontology: 5 events -- a per-mount snap-to-last would leave
    // currentIndex at 2 (showing 3 / 5, mid-history). The fix snaps
    // per-ontology, so we expect 5 / 5.
    const firstOntologyEvents = mockEvents;
    const secondOntologyEvents: TimelineEvent[] = [
      ...mockEvents,
      {
        timestamp: "2026-03-20T09:00:00Z",
        event_type: "created",
        entity_key: "cls_003",
        entity_label: "Account",
        collection: "ontology_classes",
      },
      {
        timestamp: "2026-03-22T09:00:00Z",
        event_type: "approved",
        entity_key: "cls_003",
        entity_label: "Account",
        collection: "ontology_classes",
      },
    ];

    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ data: firstOntologyEvents }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ data: secondOntologyEvents }),
      });
    global.fetch = fetchMock;

    const { rerender } = render(<VCRTimeline ontologyId="onto_first" />);

    await waitFor(() => {
      expect(screen.getByText("3 / 3")).toBeInTheDocument();
    });

    rerender(<VCRTimeline ontologyId="onto_second" />);

    await waitFor(() => {
      expect(screen.getByText("5 / 5")).toBeInTheDocument();
    });
    expect(screen.getByText("Account")).toBeInTheDocument();
  });

  it("snaps to LATEST even when new ontology has FEWER events (regression)", async () => {
    // First ontology: 3 events. User scrubs to index 0 (first event).
    // Second ontology: 2 events. The bounds-clamp branch must reset
    // currentIndex to events.length - 1 = 1 (showing 2 / 2), not stay
    // at 0.
    const fewerEvents: TimelineEvent[] = mockEvents.slice(0, 2);

    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ data: mockEvents }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ data: fewerEvents }),
      });
    global.fetch = fetchMock;

    const { rerender } = render(<VCRTimeline ontologyId="onto_first" />);

    await waitFor(() => {
      expect(screen.getByText("3 / 3")).toBeInTheDocument();
    });

    // Scrub to first event in the original ontology.
    fireEvent.change(screen.getByTestId("timeline-slider"), {
      target: { value: "0" },
    });
    await waitFor(() => {
      expect(screen.getByText("1 / 3")).toBeInTheDocument();
    });

    rerender(<VCRTimeline ontologyId="onto_second" />);

    await waitFor(() => {
      expect(screen.getByText("2 / 2")).toBeInTheDocument();
    });
  });

  it("clears the previous ontology's events while the new fetch is in flight", async () => {
    // Without the ontology-change reset, the user briefly sees the OLD
    // ontology's timeline rows (and the canvas reflects the old data)
    // until the new fetch resolves. With the fix, switching ontology
    // immediately drops fetchedEvents back to [] and the loading state
    // re-appears.
    let resolveSecondFetch: ((value: unknown) => void) | null = null;
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ data: mockEvents }),
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondFetch = resolve;
          }),
      );
    global.fetch = fetchMock;

    const { rerender } = render(<VCRTimeline ontologyId="onto_first" />);
    await waitFor(() => {
      expect(screen.getByText("3 / 3")).toBeInTheDocument();
    });

    rerender(<VCRTimeline ontologyId="onto_second" />);

    // Old events should be gone immediately, even though the new fetch
    // is still pending.
    await waitFor(() => {
      expect(screen.getByTestId("timeline-loading")).toBeInTheDocument();
    });
    expect(screen.queryByText("Organization")).not.toBeInTheDocument();

    if (resolveSecondFetch) {
      (resolveSecondFetch as (value: unknown) => void)({
        ok: true,
        json: () => Promise.resolve({ data: mockEvents }),
      });
    }
    await waitFor(() => {
      expect(screen.getByText("3 / 3")).toBeInTheDocument();
    });
  });
});
