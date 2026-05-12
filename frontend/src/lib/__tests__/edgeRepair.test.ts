import { applyEdgeRepair, previewEdgeRepair } from "../edgeRepair";

const post = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    post: (...args: unknown[]) => post(...args),
  },
  ApiError: class ApiError extends Error {},
}));

describe("edgeRepair API wrapper", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({
      ontology_id: "ont-1",
      orphans_found: 0,
      repaired_count: 0,
      unrecoverable_count: 0,
      no_domain_count: 0,
      repaired: [],
      unrecoverable: [],
      no_domain: [],
    });
  });

  it("preview hits the admin endpoint with dry_run=true", async () => {
    await previewEdgeRepair("ont-1");
    expect(post).toHaveBeenCalledWith(
      "/api/v1/admin/ontology/ont-1/repair-edges?dry_run=true",
    );
  });

  it("apply hits the admin endpoint without dry_run", async () => {
    await applyEdgeRepair("ont-1");
    expect(post).toHaveBeenCalledWith(
      "/api/v1/admin/ontology/ont-1/repair-edges",
    );
  });

  it("URI-encodes the ontology id", async () => {
    await previewEdgeRepair("ont/with slash");
    expect(post).toHaveBeenCalledWith(
      "/api/v1/admin/ontology/ont%2Fwith%20slash/repair-edges?dry_run=true",
    );
  });

  it("propagates the typed report on success", async () => {
    post.mockResolvedValueOnce({
      ontology_id: "ont-1",
      orphans_found: 3,
      repaired_count: 2,
      unrecoverable_count: 1,
      no_domain_count: 0,
      repaired: [
        {
          prop_key: "p1",
          domain_class_key: "D1",
          range_class_key: "R1",
          matched_text: "hit",
          matched_via: "label",
          other_candidates: [],
        },
      ],
      unrecoverable: [],
      no_domain: [],
    });
    const r = await applyEdgeRepair("ont-1");
    expect(r.repaired_count).toBe(2);
    expect(r.repaired[0].range_class_key).toBe("R1");
  });

  it("propagates fetch errors so callers can surface them in the UI", async () => {
    post.mockRejectedValueOnce(new Error("boom"));
    await expect(previewEdgeRepair("ont-1")).rejects.toThrow("boom");
  });
});
