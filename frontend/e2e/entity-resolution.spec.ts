import { test, expect } from "@playwright/test";

const MOCK_CANDIDATES = {
  data: [
    {
      pair_id: "pair_e2e_001",
      entity_1: {
        key: "cls_001",
        uri: "http://example.org/Person",
        label: "Person",
      },
      entity_2: {
        key: "cls_002",
        uri: "http://example.org/Individual",
        label: "Individual",
      },
      overall_score: 0.92,
      field_scores: {
        label_sim: 0.7,
        description_sim: 0.95,
        uri_sim: 0.6,
        topology_sim: 0.88,
      },
      status: "pending",
    },
    {
      pair_id: "pair_e2e_002",
      entity_1: {
        key: "cls_003",
        uri: "http://example.org/Org",
        label: "Organization",
      },
      entity_2: {
        key: "cls_004",
        uri: "http://example.org/Company",
        label: "Company",
      },
      overall_score: 0.65,
      field_scores: {
        label_sim: 0.5,
        description_sim: 0.7,
        uri_sim: 0.4,
        topology_sim: 0.8,
      },
      status: "pending",
    },
  ],
  cursor: null,
  has_more: false,
  total_count: 2,
};

const MOCK_EXPLANATION = {
  pair_id: "pair_e2e_001",
  entity_1: {
    key: "cls_001",
    uri: "http://example.org/Person",
    label: "Person",
  },
  entity_2: {
    key: "cls_002",
    uri: "http://example.org/Individual",
    label: "Individual",
  },
  overall_score: 0.92,
  fields: [
    {
      field_name: "label",
      value_1: "Person",
      value_2: "Individual",
      similarity: 0.7,
      method: "jaro_winkler",
    },
    {
      field_name: "description",
      value_1: "A human being",
      value_2: "A single person",
      similarity: 0.95,
      method: "cosine",
    },
    {
      field_name: "uri",
      value_1: "http://example.org/Person",
      value_2: "http://example.org/Individual",
      similarity: 0.6,
      method: "jaro_winkler",
    },
    {
      field_name: "topology",
      value_1: "(graph neighborhood)",
      value_2: "(graph neighborhood)",
      similarity: 0.88,
      method: "jaccard",
    },
  ],
};

const MOCK_GRAPH = {
  data: [
    {
      _key: "cls_001",
      uri: "http://example.org/Person",
      label: "Person",
      description: "A human being.",
      rdf_type: "owl:Class",
      confidence: 0.9,
      status: "pending",
      ontology_id: "onto_e2e",
      created: "2026-03-10T10:00:00Z",
      expired: null,
    },
    {
      _key: "cls_002",
      uri: "http://example.org/Individual",
      label: "Individual",
      description: "A single person.",
      rdf_type: "owl:Class",
      confidence: 0.85,
      status: "pending",
      ontology_id: "onto_e2e",
      created: "2026-03-10T10:00:00Z",
      expired: null,
    },
  ],
  cursor: null,
  has_more: false,
  total_count: 2,
};

const MOCK_CLUSTERS = {
  data: [],
  cursor: null,
  has_more: false,
  total_count: 0,
};

const MOCK_CROSS_TIER = {
  data: [],
  cursor: null,
  has_more: false,
  total_count: 0,
};

test.describe("Entity Resolution Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/er/candidates?**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_CANDIDATES),
      }),
    );

    await page.route("**/api/v1/er/candidates/pair_e2e_001/explain", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_EXPLANATION),
      }),
    );

    await page.route("**/api/v1/er/candidates/*/accept", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      }),
    );

    await page.route("**/api/v1/er/candidates/*/reject", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      }),
    );

    await page.route("**/api/v1/er/graph**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_GRAPH),
      }),
    );

    await page.route("**/api/v1/er/clusters**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_CLUSTERS),
      }),
    );

    await page.route("**/api/v1/er/cross-tier**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_CROSS_TIER),
      }),
    );

    await page.route("**/api/v1/er/entity/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          key: "cls_001",
          uri: "http://example.org/Person",
          label: "Person",
          description: "A human being.",
          rdf_type: "owl:Class",
          properties: {},
          edges: [],
        }),
      }),
    );
  });

  test("navigates to ER page and loads candidate list", async ({ page }) => {
    await page.goto("/entity-resolution");

    await expect(page.getByText("Entity Resolution")).toBeVisible();
    await expect(page.getByTestId("merge-candidates")).toBeVisible();

    await expect(
      page.getByTestId("candidate-pair_e2e_001"),
    ).toBeVisible();
    await expect(
      page.getByTestId("candidate-pair_e2e_002"),
    ).toBeVisible();

    await expect(page.getByText("Person")).toBeVisible();
    await expect(page.getByText("Individual")).toBeVisible();
  });

  test("clicking Explain shows field-by-field comparison", async ({
    page,
  }) => {
    await page.goto("/entity-resolution");

    await expect(
      page.getByTestId("explain-btn-pair_e2e_001"),
    ).toBeVisible();

    await page.getByTestId("explain-btn-pair_e2e_001").click();

    await expect(
      page.getByTestId("explanation-pair_e2e_001"),
    ).toBeVisible();
    await expect(page.getByTestId("explanation-table")).toBeVisible();
    await expect(page.getByText("label")).toBeVisible();
    await expect(page.getByText("description")).toBeVisible();
  });

  test("tabs switch between candidates, clusters, and cross-tier", async ({
    page,
  }) => {
    await page.goto("/entity-resolution");

    await expect(page.getByTestId("merge-candidates")).toBeVisible();

    await page.getByTestId("tab-clusters").click();
    await expect(page.getByTestId("no-clusters")).toBeVisible();

    await page.getByTestId("tab-cross-tier").click();
    await expect(page.getByTestId("no-cross-tier")).toBeVisible();

    await page.getByTestId("tab-candidates").click();
    await expect(page.getByTestId("merge-candidates")).toBeVisible();
  });

  test("score threshold slider filters candidates", async ({ page }) => {
    await page.goto("/entity-resolution");

    await expect(
      page.getByTestId("candidate-pair_e2e_001"),
    ).toBeVisible();
    await expect(
      page.getByTestId("candidate-pair_e2e_002"),
    ).toBeVisible();

    await page.getByTestId("score-threshold-slider").fill("80");

    await expect(
      page.getByTestId("candidate-pair_e2e_001"),
    ).toBeVisible();
    await expect(
      page.getByTestId("candidate-pair_e2e_002"),
    ).not.toBeVisible();
  });
});
