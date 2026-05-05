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

import { buildClassContextMenu } from "./class";
import type { WorkspaceContextMenuActions } from "./types";

export type ContextMenuBuilder = (
  data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
) => ContextMenuItem[];

/** Lookup table: entity kind → builder.
 *
 *  Kept partial during the incremental H.7 extraction; ``app/workspace/page.tsx``
 *  falls back to its inline switch for kinds not registered here yet. */
export const CONTEXT_MENU_BUILDERS: Partial<Record<string, ContextMenuBuilder>> = {
  class: buildClassContextMenu,
};

export { buildClassContextMenu } from "./class";
export type { WorkspaceContextMenuActions } from "./types";
