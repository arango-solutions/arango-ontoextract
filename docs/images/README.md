# Screenshot assets for the Medium article

Drop PNGs here with the exact filenames below. They're referenced by
`docs/arango-ontoextract-medium-article.md`. Each article placeholder also
carries a hidden `CAPTURE:` HTML comment with the same guidance.

## Capture conventions

- **Theme:** one consistent theme across all shots (Arango avocado-green palette).
- **Aspect:** landscape, ~1400–1600px wide (Medium renders wide images best). Hero a touch wider.
- **Redact:** use a demo ontology/DB only. Scrub org/prospect names, emails, hostnames, credentials.
- **Annotate sparingly:** at most one or two callout arrows on the hero and pipeline shots; leave the rest clean.

## Checklist

| File | Article section | What to capture | Priority |
| --- | --- | --- | --- |
| `hero-workspace.png` | Hero (top) | `/workspace` with a visually rich demo ontology: explorer (left) + Sigma.js graph (center) + VCR timeline (bottom). | Must |
| `pipeline-monitor.png` | §4 Pipeline | Run selected → pipeline DAG mid/post-run with node statuses + metrics panel (tokens, cost, confidence, agreement). | Must |
| `provenance-panel.png` | §6 Storing OWL | Left-click a class → detail panel showing quoted `evidence_text` + source chunk/slide. | Must |
| `schema-extraction-overlay.png` | §10 Schema extraction | "Extract from ArangoDB…" overlay, preview step: graph/collection checkboxes + live class/property count. Redact host. | High |
| `quality-radar.png` | §12 Quality metrics | Per-ontology quality tab: six-dimension recharts radar + 0–100 health-score traffic light. | High |
| `vcr-timeline.png` | §7 Time travel | VCR timeline scrubbed to a past event; canvas reflecting that historical state. | High |
| `imports-dag.png` | §2 Two-tier | Imports/dependency DAG overlay of a composed ontology importing 1–2 others. | Nice |
| `chunk-visual.png` | §5 Ingestion | A PPTX document's chunk view with a `[Visual: slide N]` marker + visual diagnostics counts. | Nice |
| `revisions-inbox.png` | §8 Belief revision | Revisions Inbox overlay with a CONTRADICTED/UNCERTAIN item + agent justification + accept/reject/modify. | Nice |
| `context-menu.png` | §11 Workspace | Right-click a class node → context menu (approve/reject, history, provenance, delete). | Nice |

**Minimum viable set for publishing:** the four **Must** + two **High** shots
(hero, pipeline, provenance, schema extraction, quality radar, VCR). The four
**Nice** shots add polish but aren't load-bearing.
