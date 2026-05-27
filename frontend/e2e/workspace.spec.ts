import { test, expect } from "@playwright/test";

const MOCK_LIBRARY = {
  data: [
    {
      _key: "ont_e2e",
      name: "E2E Ontology",
      tier: "local",
      status: "active",
    },
  ],
};

const MOCK_EFFECTIVE = {
  ontology_id: "ont_e2e",
  ontology_name: "E2E Ontology",
  include: "summary",
  sources: [{ ontology_id: "ont_e2e", ontology_name: "E2E Ontology" }],
  classes: [
    {
      _key: "cls_e2e",
      uri: "http://example.org/ontology#Person",
      label: "Person",
      confidence: 0.9,
      status: "approved",
      ontology_id: "ont_e2e",
      is_imported: false,
      source_ontology_id: "ont_e2e",
    },
  ],
  edges: [],
  properties: [],
  conflicts: [],
  etag: 'W/"e2e"',
  truncated: false,
};

test.describe("Workspace smoke", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/ontology/library**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_LIBRARY),
      }),
    );

    await page.route("**/api/v1/ontology/ont_e2e/effective**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_EFFECTIVE),
      }),
    );

    await page.route("**/api/v1/ontology/ont_e2e/timeline**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [] }),
      }),
    );
  });

  test("loads /workspace with asset explorer and empty canvas", async ({ page }) => {
    await page.goto("/workspace");
    await expect(page.getByTestId("section-documents")).toBeVisible();
    await expect(page.getByTestId("section-ontologies")).toBeVisible();
    await expect(page.getByTestId("workspace-canvas-pane")).toBeVisible();
  });

  test("deep-links ontologyId and renders canvas pane", async ({ page }) => {
    await page.goto("/workspace?ontologyId=ont_e2e");
    await expect(page.getByTestId("workspace-canvas-pane")).toBeVisible();
    await expect(page.getByText("E2E Ontology")).toBeVisible();
  });
});
