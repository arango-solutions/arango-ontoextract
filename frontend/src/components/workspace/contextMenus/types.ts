/**
 * Shared types for per-entity workspace context-menu builders.
 *
 * Per ``ui-architecture.mdc`` §21, every entity type that surfaces a context
 * menu owns a builder file under this directory. Each builder is a pure
 * function ``build<Entity>ContextMenu(data, actions): ContextMenuItem[]`` that
 * receives the right-clicked entity payload plus the ``WorkspaceContextMenuActions``
 * bundle below — the union of every callback / state value the original
 * monolithic ``getContextMenuItems()`` switch in ``app/workspace/page.tsx``
 * closed over.
 *
 * Keeping all closure dependencies on a single typed interface means:
 *
 * 1. The owning page assembles the bundle once and passes it down — builders
 *    have no React imports and can be unit-tested with a plain ``jest.fn()``
 *    mock per field.
 * 2. Adding a new menu item that needs new state surfaces as a single line
 *    on this interface, which is reviewed deliberately (per
 *    ``modularity-and-structure.mdc``).
 */

import type { LensType } from "@/components/workspace/LensToolbar";
import type { GraphViewMode } from "@/app/workspace/page";
import type { PerOntologyQualityApiShape } from "@/lib/perOntologyQualityDimensions";

/** Single item the asset-info side panel can show. Matches the inline
 *  ``infoPanelItem`` state in ``WorkspacePageInner``. */
export type InfoPanelItem = {
  type: "document" | "ontology" | "run";
  data: Record<string, unknown>;
};

/** Argument shape for ``setFeedbackLearning`` (``null`` closes the overlay). */
export type FeedbackLearningArg = {
  ontologyId?: string | null;
  ontologyName?: string | null;
} | null;

/** Argument shape for ``setRenameOntology``. */
export type RenameOntologyArg = {
  key: string;
  name: string;
  description: string;
} | null;

/** Argument shape for ``setReleaseOntology``. */
export type ReleaseOntologyArg = {
  key: string;
  currentReleaseVersion?: string | null;
} | null;

/** Argument shape for ``setManageImports``. */
export type ManageImportsArg = {
  key: string;
  name: string;
} | null;

/** Layout modes accepted by ``viewportApi.relayout``. */
export type SigmaLayoutMode = "force" | "circular" | "grid" | "random";

/** Edge styles accepted by ``viewportApi.setEdgeStyle``. */
export type SigmaEdgeStyle = "curved" | "straight";

/**
 * Quality-report fetcher signature, mirroring ``fetchOntologyQualityReport``.
 *
 * The current implementation populates a ``PerOntologyQualityApiShape`` overlay
 * from an ontology row; it is exposed here only so the ``ontology`` builder can
 * trigger it without binding to the page's React state.
 */
export type FetchOntologyQualityReport = (
  ontologyData: Record<string, unknown>,
) => Promise<void> | void;

/** Setter for the side overlay holding the latest quality report payload. */
export type SetQualityOverlay = (
  overlay: { name: string; data: PerOntologyQualityApiShape } | null,
) => void;

/**
 * Unified callback bundle handed to every per-entity builder.
 *
 * **Ordering inside this interface mirrors the on-screen menu groups** in
 * ``ui-architecture.mdc`` §7 (selection, curation, destructive, life-cycle,
 * pipeline, lens / layout, viewport, contextual data). That makes the
 * "is this knob already wired?" question answerable in one pass.
 */
export interface WorkspaceContextMenuActions {
  // ── Selection / view ──────────────────────────────────────────────────
  handleNodeSelect: (classKey: string) => void;
  handleEdgeSelect: (edgeKey: string) => void;
  handleSelectOntology: (ontologyId: string) => void;
  handleSelectRun: (runId: string, ontologyId?: string) => void;
  setInfoPanelItem: (item: InfoPanelItem | null) => void;
  setDetailPanelOpen: (open: boolean) => void;
  setQualityOverlay: SetQualityOverlay;
  fetchOntologyQualityReport: FetchOntologyQualityReport;

  // ── Curation mutations ────────────────────────────────────────────────
  approveClass: (classKey: string) => void;
  rejectClass: (classKey: string) => void;
  approveEdge: (edgeKey: string) => void;
  rejectEdge: (edgeKey: string) => void;
  approveProperty: (propKey: string, ontologyId?: string) => void;
  rejectProperty: (propKey: string, ontologyId?: string) => void;

  // ── Destructive ───────────────────────────────────────────────────────
  // ``confirm()`` calls live at call sites today (H.6 territory). Builders
  // wrap each delete in the same ``window.confirm`` until that PR lands.
  deleteClass: (classKey: string) => void;
  deleteOntology: (ontologyKey: string) => void;
  deleteDocument: (docKey: string) => void;
  deleteRun: (runKey: string) => void;

  // ── Ontology life-cycle / dialogs ─────────────────────────────────────
  setRenameOntology: (arg: RenameOntologyArg) => void;
  setReleaseOntology: (arg: ReleaseOntologyArg) => void;
  setShowCreateOntology: (show: boolean) => void;
  setManageImports: (arg: ManageImportsArg) => void;
  setFeedbackLearning: (arg: FeedbackLearningArg) => void;
  exportOntology: (ontologyKey: string, format: "turtle" | "jsonld" | "csv") => void;

  // ── Pipeline ──────────────────────────────────────────────────────────
  retryRun: (runKey: string) => void;
  pipelineRunId: string | null;

  // ── Lens / graph style (canvas menu only) ─────────────────────────────
  activeLens: LensType;
  setActiveLens: (lens: LensType) => void;
  graphViewMode: GraphViewMode;
  setGraphViewMode: (mode: GraphViewMode) => void;

  // ── Sigma viewport / pipeline DAG ─────────────────────────────────────
  // All viewport methods are no-ops until the canvas mounts; this matches the
  // pre-refactor behaviour where ``viewportApiRef.current?.foo()`` would silently
  // skip when the ref was unset.
  fitAllNodes: () => void;
  centerView: () => void;
  relayout: (mode: SigmaLayoutMode) => void;
  setEdgeStyle: (style: SigmaEdgeStyle) => void;
  fitPipelineView: () => void;
  centerPipelineView: () => void;

  // ── Misc ──────────────────────────────────────────────────────────────
  /** Dismiss the open context menu — used by viewport ops that need the
   *  menu out of the way before they relayout / scroll. */
  closeContextMenu: () => void;
  /** Currently-loaded ontology, needed by the property builder to fall back
   *  to a sensible default ``ontology_id`` when the property row is missing
   *  one (e.g. legacy rows). */
  selectedOntologyId: string | null;
}
