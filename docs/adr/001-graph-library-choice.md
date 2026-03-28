# ADR 001: Graph Visualization Library Choice

**Status:** Accepted
**Date:** 2026-03-15
**Decision Makers:** AOE Core Team

---

## Context

The AOE Visual Curation Dashboard requires an interactive graph visualization component for rendering ontology class hierarchies, relationship edges, and enabling actions like approve/reject/edit/merge on individual nodes. The graph must:

- Render inside a React/Next.js application as native components
- Support interactive node/edge manipulation (click, drag, select, multi-select)
- Support custom node renderers (confidence coloring, status badges, provenance links)
- Handle graphs with 500+ nodes at < 2 second render time
- Support layout algorithms (hierarchical, force-directed)
- Enable right-click context menus and edge action panels

The two leading candidates evaluated were:

1. **React Flow** — a React-native graph rendering library
2. **Cytoscape.js** — a mature, framework-agnostic graph visualization library (used via `react-cytoscapejs` wrapper)

## Decision

We chose **React Flow** as the graph visualization library for the curation dashboard.

## Rationale

### React Flow Advantages

| Factor | React Flow | Cytoscape.js |
|--------|-----------|-------------|
| React integration | Native React components; nodes are React elements with full JSX/hooks support | Wrapper (`react-cytoscapejs`) bridges imperative API to React; custom nodes require non-React rendering callbacks |
| Custom node renderers | Each node is a React component — can embed buttons, badges, tooltips, form inputs naturally | Custom node rendering uses Cytoscape's HTML layer or canvas drawing — not React components |
| State management | Integrates naturally with React state, context, and Zustand/Redux | Requires manual synchronization between Cytoscape internal state and React state |
| Bundle size | ~45KB gzipped | ~170KB gzipped (core + layout plugins) |
| TypeScript support | First-class TypeScript definitions | Adequate but community-maintained types for some plugins |
| Layout algorithms | Built-in dagre layout; extensible via plugins | Richer built-in layout algorithms (cola, cose-bilkent, dagre, etc.) |

### Cytoscape.js Advantages (Acknowledged Trade-offs)

- **Superior layout algorithms** — more out-of-the-box layout options, especially for large complex graphs
- **Better large graph performance** — canvas-based rendering handles 10,000+ node graphs more efficiently than React Flow's DOM-based approach
- **Mature graph analysis** — built-in graph theory algorithms (BFS, DFS, shortest path)

### Why React Flow Wins for AOE

1. **Custom node UX is critical.** The curation dashboard's primary interaction is clicking nodes to approve/reject/edit — each node needs React buttons, confidence badges, status indicators, and provenance links. React Flow makes every node a React component, while Cytoscape.js requires non-React rendering.

2. **Target graph size is moderate.** Ontology graphs typically have 50–500 nodes. React Flow performs well within this range (< 2s render at 500 nodes). Cytoscape's large-graph advantage is not needed.

3. **Frontend consistency.** The team uses React hooks, Zustand, and Next.js conventions throughout. React Flow integrates seamlessly; Cytoscape.js requires an impedance-mismatch bridge layer.

4. **Development velocity.** React Flow's API is simpler for React developers. Custom node components are standard React — no need to learn Cytoscape's extension system.

## Consequences

### Positive

- Custom curation nodes (approve/reject buttons, confidence indicators) are standard React components
- Graph state management integrates naturally with the rest of the React application
- Smaller bundle size
- Faster developer onboarding for React-experienced team

### Negative

- Fewer built-in layout algorithms — dagre covers hierarchical ontology visualization, but additional layouts may require custom implementation
- DOM-based rendering will become a bottleneck if graphs exceed ~2,000 nodes — at that point, virtualization or server-side filtering would be needed
- Some graph analysis features (centrality, shortest path) are not available natively and would need to be computed server-side via AQL

### Mitigations

- Lazy loading and server-side filtering for large ontologies (only load visible subgraph)
- Layout computation can be offloaded to Web Workers if needed
- Graph analysis is done in ArangoDB via AQL traversals, not in the browser
