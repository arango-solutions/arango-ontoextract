# UI screenshots

Images used by the root [`README.md`](../../README.md) and
[`docs/user-guide.md`](../user-guide.md).

## Current images

| File | Used in | Description |
|------|---------|-------------|
| `workspace-hero.png` | README hero + "Using the Workspace UI" | The `/workspace` stage: asset explorer, graph canvas, lens legend, floating class detail panel, VCR timeline |

## Wanted screenshots (shot list)

Contributions welcome — these would make the README and user guide much more
inviting to new users. Capture at a **1440×900** (or larger 16:10) viewport,
light theme, with the **Financial Services Domain** sample ontology loaded so
shots are consistent. Save as PNG with the filename below and add a row to the
table above plus the embed in the relevant doc.

| Suggested file | What it should show |
|----------------|---------------------|
| `upload-document.png` | Dragging a PDF/PPTX into the asset explorer; the parse → chunk → embed status chips |
| `extract-run.png` | The pipeline DAG mid-run, with per-agent steps and live WebSocket progress |
| `curation-menu.png` | A right-click context menu open on a class node (Approve / Reject / View provenance / Delete) |
| `lens-confidence.png` | The graph under the **Confidence** lens with the lens legend explaining the encoding |
| `vcr-timeline.png` | The VCR timeline scrubbed to a past point, showing a temporal diff |
| `detail-panel.png` | A floating class detail panel open (left-click selection) beside the canvas |
| `promote-production.png` | The promote-to-production overlay / confirmation flow |

## Guidelines

- Use real (or realistic sample) data — never fabricated/mocked screens that
  don't match the shipping UI. An inaccurate screenshot is worse than none.
- Crop to the relevant region; avoid capturing OS chrome or unrelated browser
  tabs.
- Keep file sizes reasonable (prefer < 500 KB; use PNG optimization).
- Always include descriptive alt text in the markdown embed for accessibility.
