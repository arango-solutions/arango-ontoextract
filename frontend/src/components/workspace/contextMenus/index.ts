/**
 * Per-entity workspace context-menu builder registry.
 *
 * The registry below replaces the 670-line ``getContextMenuItems()`` switch
 * that previously lived in ``app/workspace/page.tsx``. The page assembles a
 * single ``WorkspaceContextMenuActions`` bundle, looks up the builder for
 * the right-clicked entity type via ``CONTEXT_MENU_BUILDERS``, and calls it.
 *
 * Adding a new entity type:
 *   1. Add a builder file ``./<entity>.ts`` exporting
 *      ``build<Entity>ContextMenu(data, actions)``.
 *   2. Register it in ``CONTEXT_MENU_BUILDERS`` below (lower-cased entity
 *      kind matching the string emitted by ``setContextMenu``).
 *   3. Add a sibling test ``__tests__/<entity>.test.ts`` per
 *      ``ui-architecture.mdc`` §22.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";

import { buildCanvasContextMenu } from "./canvas";
import { buildClassContextMenu } from "./class";
import { buildDocumentContextMenu } from "./document";
import { buildEdgeContextMenu } from "./edge";
import { buildOntologyContextMenu } from "./ontology";
import { buildPipelineCanvasContextMenu } from "./pipelineCanvas";
import { buildPropertyContextMenu } from "./property";
import { buildRunContextMenu } from "./run";
import { buildStepContextMenu } from "./step";
import type { WorkspaceContextMenuActions } from "./types";

export type ContextMenuBuilder = (
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
) => ContextMenuItem[];

/** Lookup table: entity kind → builder.
 *
 *  ``Partial`` rather than full ``Record`` so unrecognised kinds (e.g. a
 *  future ``setContextMenu({ type: "annotation" })``) yield ``undefined``
 *  and the page returns an empty menu, matching the pre-refactor
 *  ``default: return []`` branch. */
export const CONTEXT_MENU_BUILDERS: Partial<Record<string, ContextMenuBuilder>> = {
  canvas: buildCanvasContextMenu,
  class: buildClassContextMenu,
  document: buildDocumentContextMenu,
  edge: buildEdgeContextMenu,
  ontology: buildOntologyContextMenu,
  pipeline_canvas: buildPipelineCanvasContextMenu,
  property: buildPropertyContextMenu,
  run: buildRunContextMenu,
  step: buildStepContextMenu,
};

export { buildCanvasContextMenu } from "./canvas";
export { buildClassContextMenu } from "./class";
export { buildDocumentContextMenu } from "./document";
export { buildEdgeContextMenu } from "./edge";
export { buildOntologyContextMenu } from "./ontology";
export { buildPipelineCanvasContextMenu } from "./pipelineCanvas";
export { buildPropertyContextMenu } from "./property";
export { buildRunContextMenu } from "./run";
export { buildStepContextMenu } from "./step";
export type { WorkspaceContextMenuActions } from "./types";
