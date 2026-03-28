---
name: arangodb-visualizer-customizer
description: Installs and maintains ArangoDB Graph Visualizer customization assets (themes, saved queries, canvas actions, and viewpoint links). Use when the user mentions ArangoDB visualizer, Graph Visualizer, themes, canvas actions, saved queries, stored queries, or collections like _graphThemeStore, _canvasActions, _editor_saved_queries, _viewpoints, or _viewpointActions.
---

# ArangoDB Visualizer Customizer (themes, saved queries, canvas actions)

This skill provides a repeatable, idempotent workflow for customizing the ArangoDB **Graph Visualizer** by installing:

- **Themes** (colors/icons) in `_graphThemeStore`
- **Saved queries** in `_editor_saved_queries`
- **Canvas actions** in `_canvasActions`
- **Viewpoint links** (so actions show up in the UI) in `_viewpointActions` edges from `_viewpoints/*` → `_canvasActions/*`

## Quick start checklist (most reliable order)

1. **Confirm graph + DB**: target database name and graph name (e.g. `IC_Knowledge_Graph`).
2. **Create or ensure a viewpoint exists**:
   - **Programmatic** (preferred): insert a "Default" doc into `_viewpoints` with `graphId`, `name`, `description`, `createdAt`, `updatedAt`. See "Programmatic viewpoint creation" below.
   - **Manual**: open the graph once in the web UI (Graphs → your graph). This auto-creates `_viewpoints` docs.
3. **Install theme** (target DB):
   - Upsert into `_graphThemeStore` (by `graphId` + `name`).
   - Set `isDefault: true` on the custom theme so it auto-applies.
   - Also install a plain "Default" theme (`isDefault: false`) so the user can switch back.
4. **Install saved queries** (often `_system`, sometimes target DB):
   - Upsert into `_editor_saved_queries`.
   - **CRITICAL**: The query editor reads the **`content`** field, NOT `queryText`. Use `content` for the AQL text.
5. **Install canvas actions** (often `_system`, sometimes target DB):
   - Upsert into `_canvasActions`.
   - Canvas actions use `queryText` (different from saved queries which use `content`).
   - Ensure each action has `name` (UI expects it) and a stable `_key`.
6. **Link actions to the viewpoint** (target DB):
   - Insert edges in `_viewpointActions` from the correct `_viewpoints/_id` to `_canvasActions/<_key>`.
7. **Verify**:
   - Counts look sane; actions appear in UI right-click menu; queries appear in Queries panel with AQL visible; theme selectable in Legend.

## Key implementation details (what the agent must know)

### Where these "special collections" live

ArangoDB UI metadata may be stored either:

- **In the target database**, or
- **In `_system`** (common for `_editor_saved_queries` / `_canvasActions`)

Best practice:

- Treat **themes** as **target-DB** assets (install into the same DB as the graph).
- Treat **saved queries** and **canvas actions** as **system-level** assets by default (install into `_system`) *but* fall back to target DB if `_system` is locked down or the environment clearly uses target DB for those collections.
- When creating `_`-prefixed collections via `python-arango`, pass `system=True`: `db.create_collection(name, system=True)`.

### Viewpoints and linking canvas actions

Canvas actions do **not** show up in Graph Visualizer until they are linked to a graph "viewpoint".

- Viewpoints live in: `_viewpoints` (target DB)
- Links live in: `_viewpointActions` (edge collection, target DB)
- Edge shape:
  - `_from`: the viewpoint `_id` (e.g. `_viewpoints/12345`)
  - `_to`: the action `_id` (commonly `_canvasActions/<action_key>`)

#### Programmatic viewpoint creation

Instead of requiring the user to open the graph in the UI first, create a "Default" viewpoint programmatically:

```python
def ensure_default_viewpoint(db, graph_name: str) -> str:
    ensure_collection(db, "_viewpoints")
    vp_col = db.collection("_viewpoints")
    existing = list(vp_col.find({"graphId": graph_name, "name": "Default"}))
    if existing:
        return existing[0]["_id"]
    now = datetime.utcnow().isoformat() + "Z"
    res = vp_col.insert({
        "graphId": graph_name,
        "name": "Default",
        "description": f"Default viewpoint for {graph_name}",
        "createdAt": now,
        "updatedAt": now,
    })
    return res["_id"]
```

This eliminates the manual "open graph in UI first" step and allows fully automated deployment.

### Minimal document shapes (use these defaults)

**Theme document** (`_graphThemeStore`):
- Must include `name`, `graphId`, `nodeConfigMap`, `edgeConfigMap`
- Set **`isDefault: true`** on the custom theme so it auto-applies when the graph is opened
- Also install a plain "Default" theme with `isDefault: false` (dropping/recreating the database loses the built-in default theme)
- Add/refresh timestamps: `createdAt`, `updatedAt`
- Upsert key: `graphId + name`

#### Theme node config structure (`nodeConfigMap`)

Each key is a vertex collection name. The value must use this exact structure:

```json
{
  "Device": {
    "background": { "color": "#2563eb", "iconName": "fa6-solid:server" },
    "labelAttribute": "name",
    "hoverInfoAttributes": ["name", "type", "ipAddress", "tenantId"],
    "rules": []
  }
}
```

Fields:
- **`background.color`**: hex color string
- **`background.iconName`**: Font Awesome 6 icon ID (e.g. `fa6-solid:server`, `fa6-solid:cube`, `fa6-solid:location-dot`, `fa6-solid:triangle-exclamation`, `fa6-solid:shapes`, `fa6-solid:building`, `fa6-solid:user`, `fa6-solid:credit-card`)
- **`labelAttribute`**: document field to display as the node label (e.g. `"name"`, `"_key"`)
- **`hoverInfoAttributes`**: array of field names shown on hover
- **`rules`**: array of conditional styling rules (e.g. `[{"name": "High Risk", "condition": "riskScore >= 80", "background": {"color": "#e53e3e"}}]`)

**DO NOT** use flat fields like `color`, `icon`, `label`, `size`, `tooltip` — these are not recognized by the Visualizer.

#### Theme edge config structure (`edgeConfigMap`)

Each key is an edge collection name:

```json
{
  "hasConnection": {
    "lineStyle": { "color": "#6366f1", "thickness": 1.2 },
    "arrowStyle": { "sourceArrowShape": "none", "targetArrowShape": "triangle" },
    "hoverInfoAttributes": ["connectionType", "bandwidthCapacity"],
    "rules": [],
    "labelStyle": { "color": "#1d2531" }
  }
}
```

#### ensure_visualizer_shape() helper

After building a theme document, call this to add required defaults for any missing fields:

```python
def ensure_visualizer_shape(theme: dict) -> None:
    for node_cfg in theme.get("nodeConfigMap", {}).values():
        node_cfg.setdefault("rules", [])
        node_cfg.setdefault("hoverInfoAttributes", [])
    for edge_cfg in theme.get("edgeConfigMap", {}).values():
        edge_cfg.setdefault("rules", [])
        edge_cfg.setdefault("hoverInfoAttributes", [])
        edge_cfg.setdefault("arrowStyle", {"sourceArrowShape": "none", "targetArrowShape": "triangle"})
        edge_cfg.setdefault("labelStyle", {"color": "#1d2531"})
```

#### prune_theme() helper

Prune theme configs to only include collections that actually exist in the graph:

```python
def prune_theme(theme_raw: dict, vertex_colls: set, edge_colls: set) -> dict:
    import copy
    theme = copy.deepcopy(theme_raw)
    if "nodeConfigMap" in theme:
        theme["nodeConfigMap"] = {k: v for k, v in theme["nodeConfigMap"].items() if k in vertex_colls}
    if "edgeConfigMap" in theme:
        theme["edgeConfigMap"] = {k: v for k, v in theme["edgeConfigMap"].items() if k in edge_colls}
    return theme
```

**Saved query** (`_editor_saved_queries`):
- **CRITICAL**: Use **`content`** for the AQL query text. The ArangoDB query editor reads this field. Do NOT use `queryText` — that field is only for canvas actions.
- Use `title` and `name` for display
- Optionally include: `description`, `bindVariables`
- If the UI expects database scoping, add a `databaseName` field set to the target DB
- Upsert key: stable `_key` when possible; otherwise match on `title`/`name`

Example saved query document:

```json
{
  "_key": "tenant_overview",
  "title": "Tenant Overview",
  "name": "Tenant Overview",
  "description": "Summary of all tenants with device counts",
  "content": "FOR d IN Device\n  COLLECT tenant = d.tenantId WITH COUNT INTO c\n  RETURN {tenant, count: c}",
  "bindVariables": {},
  "databaseName": "my-database"
}
```

**Canvas action** (`_canvasActions`):
- Use stable `_key` (snake_case), plus `name`, `title`, **`queryText`** (NOT `content`), `graphId`, `bindVariables`
- If `title` exists but `name` doesn't, set `name = title` (UI requires `name` in practice)
- Upsert key: `_key` (preferred) or match on `name`
- **`bindVariables` for node-based actions**: Use `{"nodes": []}`. The node selector provides an array of selected vertices/edges; the query receives them as `@nodes`. Use `FOR node IN @nodes` directly. Do not add `IS_ARRAY` normalization or empty-result fallbacks — the Visualizer expects the query to return paths/edges in the standard format.
- **`WITH` clause**: Required for cluster deployments. List all vertex and edge collections that may be encountered in the traversal.
- **`RETURN` value**: Return edges (`RETURN e`) or paths (`RETURN p`), not vertices. The Visualizer renders these as graph expansions.

Example canvas action pattern:

```python
with_clause = "WITH " + ", ".join(sorted(vertex_colls | edge_colls))
edge_list_str = ", ".join(sorted(edge_colls))

default_query = f"""{with_clause}
FOR node IN @nodes
  FOR v, e IN 1..2 ANY node GRAPH "{graph_name}"
  LIMIT 100
  RETURN e"""

per_collection_query = f"""{with_clause}
FOR node IN @nodes
  FILTER IS_SAME_COLLECTION("{v_coll}", node)
  FOR v, e, p IN 1..1 ANY node {edge_list_str}
  LIMIT 20
  RETURN p"""
```

### Field name summary (critical — do not confuse)

| Collection | Field for AQL | Notes |
|---|---|---|
| `_editor_saved_queries` | **`content`** | `queryText` is IGNORED by the query editor UI |
| `_canvasActions` | **`queryText`** | `content` is NOT used for canvas actions |

### Idempotency rules (must follow)

When installing:
- **Never create duplicates**.
- Prefer **upsert/update**:
  - If a doc exists → update content and set `updatedAt`
  - If missing → insert with stable `_key` and set `createdAt`/`updatedAt`
- For viewpoint links:
  - Insert only if an edge with same `_from` and `_to` does not already exist.
- Use `check_rev=False` on replace/update operations to avoid revision conflicts.

## Recommended workflow to implement in a project

### 1) Create "installer" scripts in the repo

Include scripts that can be run repeatedly:
- `scripts/setup/install_visualizer.py` — single consolidated installer for all assets
- Or separate scripts: `install_theme.py`, `install_queries.py`, `install_actions.py`

Prefer Python + `python-arango`.

### 2) Store assets in version control

Keep assets as JSON files under `docs/visualizer/`:
- `docs/visualizer/<graph_name>_theme.json`
- `docs/visualizer/<graph_name>_saved_queries.json`

This makes the DB customization reproducible and reviewable.

### 3) Integrate into deployment pipeline

Install visualizer assets as the final step of database deployment so they survive database drops and recreations.

### 4) Verify in UI (manual steps)

- Graph Visualizer:
  - **Theme**: Graphs → graph → Legend → theme dropdown (custom theme should auto-apply if `isDefault: true`)
  - **Icons**: nodes should show Font Awesome icons, not generic shapes
  - **Saved queries**: Queries panel — click a query and verify AQL text appears (not empty)
  - **Canvas actions**: right-click node/canvas → Canvas Actions submenu

### Ontology vs data graphs

For **ontology graphs** (metadata only: classes, properties, domain/range):
- Restrict theme `nodeConfigMap` and `edgeConfigMap` to ontology collections (Class, Property, Ontology, ObjectProperty, DatatypeProperty, OntologyGraph_UnknownResource; domain, range, subClassOf, type).
- Restrict canvas actions to ontology vertex types only. Do not create expand actions for data collections (Person, Organization, etc.) — they don't belong in an ontology view.
- For DatatypeProperty/ObjectProperty expand actions: filter on the *traversed* vertex `v`, not the start `node` (e.g. `FILTER IS_SAME_COLLECTION("DatatypeProperty", v)`), and use ontology edges only (domain, range, subClassOf — omit type if not needed).

### Cluster deployments

- Include a `WITH` clause listing all vertex and edge collections that may be encountered in the traversal (required for cluster mode).

## Troubleshooting (common failures)

### Actions don't appear
- `_viewpoints` empty → create programmatically with `ensure_default_viewpoint()` or open graph in UI once.
- Wrong viewpoint selected → choose viewpoint whose `graphId` matches the actions' `graphId`.
- Missing `_viewpointActions` edge collection or edges not created.

### Queries appear but are empty in the editor
- **Wrong field name**: the query editor reads **`content`**, not `queryText`. Check the documents in `_editor_saved_queries` and ensure AQL is in the `content` field.

### Queries appear but run against wrong DB
- Ensure query doc includes `databaseName` (if used in your environment).
- Ensure `bindVariables` include correct vertex IDs (e.g. `RTL_Module/or1200_cpu`) for the target DB.

### Theme not selectable
- `_graphThemeStore` missing in target DB → create the collection with `system=True`.
- Theme `graphId` does not match actual graph name in DB.

### Theme doesn't auto-apply
- Missing `isDefault: true` on the theme document. The Visualizer only auto-applies themes marked as default.

### Icons show as generic shapes
- Wrong field structure. Use `"background": {"color": "#hex", "iconName": "fa6-solid:icon-name"}`, NOT flat fields like `"color"`, `"icon"`.
- Invalid icon name. Icons must use Font Awesome 6 format: `fa6-solid:server`, `fa6-solid:cube`, etc.

### Default theme missing after database recreation
- Dropping and recreating the database loses the built-in default theme. Always install a plain "Default" theme (`isDefault: false`) alongside custom themes.

### Collection creation fails with "illegal name"
- `_`-prefixed collections require `system=True` in `python-arango`: `db.create_collection("_graphThemeStore", system=True)`.

## Concrete reference (existing working examples)

Use these as "known-good" templates:
- `fraud-intelligence/scripts/install_graph_themes.py` — themes + canvas actions; ontology-only handling; `ensure_default_viewpoint()` pattern; `ensure_visualizer_shape()` helper
- `fraud-intelligence/docs/themes/ontology_theme.json` — correct theme structure with `background`, `iconName`, `labelAttribute`, `hoverInfoAttributes`, `rules`
- `fraud-intelligence/docs/themes/datagraph_theme.json` — data graph theme with conditional rules (risk-based coloring)
- `ic-knowledge-graph/scripts/setup/install_demo_setup.py` — saved queries using `content` field
- `ic-knowledge-graph/scripts/setup/install_graphrag_queries.py` — saved queries + canvas actions
- `ic-knowledge-graph/docs/DEMO_SETUP_QUERIES.json` — JSON format for saved queries (`content` field, `bindVariables`, `databaseName`)
- `network-asset-management-demo/scripts/setup/install_visualizer.py` — consolidated installer for multiple graphs with `_ensure_default_theme()`
