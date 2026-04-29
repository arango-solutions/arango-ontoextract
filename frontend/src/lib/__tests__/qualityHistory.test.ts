import { loadQualityHistory } from "../qualityHistory";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
  },
}));

describe("loadQualityHistory", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ ontology_id: "onto 1", count: 0, snapshots: [] });
  });

  it("loads encoded ontology history with optional limit", async () => {
    const result = await loadQualityHistory("onto 1", { limit: 25 });

    expect(result.count).toBe(0);
    expect(get).toHaveBeenCalledWith("/api/v1/quality/onto%201/history?limit=25");
  });

  it("omits query params when no options are provided", async () => {
    await loadQualityHistory("onto_1");

    expect(get).toHaveBeenCalledWith("/api/v1/quality/onto_1/history");
  });
});
