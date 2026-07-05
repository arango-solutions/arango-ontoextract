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

/** Argument shape for ``setDependencyOverlay`` (``null`` closes the overlay).
 *  Drives the H.7 ``ImportsDependencyOverlay`` — DAG visualisation of
 *  ``owl:imports`` ancestors + dependents anchored at one ontology. */
export type DependencyOverlayArg = {
  key: string;
  name: string;
} | null;

/** Argument shape for ``setSchemaDiffOverlay`` (``null`` closes the overlay).
 *  Drives the Stream 5 S.5 ``SchemaDiffOverlay`` — cross-ontology schema
 *  evolution diff between two registry ontologies. */
export type SchemaDiffOverlayArg = {
  key: string;
  name: string;
} | null;

/** Argument shape for ``setEdgeRepair`` (``null`` closes the overlay). */
export type EdgeRepairArg = {
  key: string;
  name: string;
} | null;

/** Argument shape for ``setRevisionsInbox`` (``null`` closes the overlay). */
export type RevisionsInboxArg = {
  key: string;
  name: string;
} | null;

/** Argument shape for ``setMergeCandidates`` (``null`` closes the overlay).
 *  Drives the Stream 2 ``MergeCandidatesOverlay``: triggers an ER pipeline
 *  run for the named ontology and lists merge candidate pairs for
 *  curator decision. Same overlay-not-route rule (``ui-architecture.mdc``
 *  rule 9). */
export type MergeCandidatesArg = {
  key: string;
  name: string;
} | null;

/** Argument shape for ``setOntologyDelete`` (``null`` closes the dialog).
 *  Drives the H.4 ``OntologyDeleteDialog``: fetches a deletion-impact
 *  preview before allowing the typed-name confirmation. */
export type OntologyDeleteArg = {
  key: string;
  name: string;
} | null;

/** Typed-name confirmation gate for ``ConfirmRequest``. Mirrors
 *  ``ConfirmDialogTypedName`` in ``ConfirmDialog.tsx`` so builders don't have
 *  to import the React component just to reference the type. */
export interface ConfirmTypedName {
  expected: string;
  label: string;
  placeholder?: string;
}

/** A single ``ConfirmDialog`` request emitted by a builder. The page owns the
 *  state that holds the latest request and renders the dialog from it; per
 *  ``ui-architecture.mdc`` §18 this surface replaces every ``window.confirm``
 *  in the workspace. */
export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** When omitted, defaults to ``true`` (red styling) — this surface exists
   *  primarily for destructive ops. */
  danger?: boolean;
  /** When set, switches the rendered dialog into typed-name mode. */
  typedName?: ConfirmTypedName;
  /** Fired when the user clicks Confirm. The page closes the dialog before
   *  invoking this so the caller doesn't need to thread a separate close. */
  onConfirm: () => void;
}

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
  // Builders that need a confirmation gate (delete class / run / ontology)
  // call ``requestConfirm`` instead of ``window.confirm``; the page owns
  // the dialog state and renders ``<ConfirmDialog>``. The bare delete
  // callbacks below stay as-is so non-gated callers (e.g. the side panel
  // delete buttons) keep working.
  deleteClass: (classKey: string) => void;
  deleteOntology: (ontologyKey: string) => void;
  deleteDocument: (docKey: string) => void;
  deleteRun: (runKey: string) => void;
  requestConfirm: (request: ConfirmRequest) => void;
  /** Open the H.4 ``OntologyDeleteDialog`` -- typed-name confirmation
   *  with a cascade-on-delete dependency preview. Replaces the inline
   *  ``requestConfirm`` flow that previously gated ontology deletes,
   *  because the impact analysis must be visible before the user is
   *  asked to confirm. ``null`` closes the dialog. */
  setOntologyDelete: (arg: OntologyDeleteArg) => void;

  // ── Ontology life-cycle / dialogs ─────────────────────────────────────
  setRenameOntology: (arg: RenameOntologyArg) => void;
  setReleaseOntology: (arg: ReleaseOntologyArg) => void;
  setShowCreateOntology: (show: boolean) => void;
  /** Opens the H.6 ``CatalogBrowserOverlay`` — one-click import of
   *  standard ontologies from the bundled catalog. Overlay, not a
   *  route, per ``ui-architecture.mdc`` rule 9. */
  setShowCatalogBrowser: (show: boolean) => void;
  /** Opens the Stream 5 PR 2 ``SchemaExtractionOverlay`` — connect to
   *  an external ArangoDB, discover its named graphs + loose
   *  collections, and reverse-engineer the topology into a new AOE
   *  ontology. Overlay, not a route, per ``ui-architecture.mdc`` rule
   *  9. Same surface as Catalog Browse: both are add-an-ontology
   *  actions opened from the canvas right-click menu. */
  setShowSchemaExtraction: (show: boolean) => void;
  /** Opens the ``RelationalExtractionOverlay`` — connect to a relational
   *  database (PostgreSQL / MySQL / SQL Server / Snowflake / DuckDB /
   *  Databricks / CSV), preview its tables + foreign keys, and
   *  reverse-engineer them into a new AOE ontology. Overlay, not a route,
   *  per ``ui-architecture.mdc`` rule 9. Same add-an-ontology surface as
   *  the ArangoDB schema extraction, opened from the canvas menu. */
  setShowRelationalExtraction: (show: boolean) => void;
  setManageImports: (arg: ManageImportsArg) => void;
  /** Opens the H.7 ``ImportsDependencyOverlay`` — DAG canvas of the
   *  ``owl:imports`` ancestors and dependents of one ontology, sourced
   *  from ``GET /api/v1/ontology/imports-graph``. Click-to-navigate
   *  re-roots the graph and (when the user accepts the navigation hint)
   *  switches the workspace selection. ``null`` closes the overlay. */
  setDependencyOverlay: (arg: DependencyOverlayArg) => void;
  /** Opens the Stream 5 S.5 ``SchemaDiffOverlay`` — compare schema evolution
   *  between two ontologies via ``GET /schema/diff``. ``null`` closes. */
  setSchemaDiffOverlay: (arg: SchemaDiffOverlayArg) => void;
  setFeedbackLearning: (arg: FeedbackLearningArg) => void;
  /** Opens the ``EdgeRepairOverlay`` for one ontology -- preview +
   *  apply for orphan ``ontology_object_properties`` (R3 violations).
   *  ``null`` closes the overlay. Per ``ui-architecture.mdc`` rule 9
   *  this surface is an overlay over the workspace canvas, never a
   *  separate route. */
  setEdgeRepair: (arg: EdgeRepairArg) => void;
  /** Opens the ``RevisionsInboxOverlay`` for one ontology — pending
   *  FLAG_FOR_CURATION revisions from the belief-revision pipeline.
   *  ``null`` closes the overlay. Same overlay-not-route rule. */
  setRevisionsInbox: (arg: RevisionsInboxArg) => void;
  /** Opens the Stream 2 ``MergeCandidatesOverlay`` for one ontology —
   *  triggers an ER pipeline run, then lets the curator accept /
   *  reject each duplicate candidate pair. ``null`` closes the
   *  overlay. Same overlay-not-route rule. */
  setMergeCandidates: (arg: MergeCandidatesArg) => void;
  exportOntology: (ontologyKey: string, format: "turtle" | "jsonld" | "csv") => void;

  // ── Imports (Stream 1 H.16) ───────────────────────────────────────────
  /** Soft-delete the ``imports`` edge from the currently-open ontology to
   *  ``importedOntologyId`` and refresh the canvas. Used by the "Remove
   *  Import (<source name>)" entries on imported class / edge context
   *  menus. The page-level implementation shows an undo / failure toast
   *  via the global toast surface and bumps the explorer's library
   *  reload nonce so the imports-graph DAG (H.7) re-reads. ``import-
   *  edOntologyName`` is forwarded so toast copy can name the source. */
  removeImportEdge: (
    importedOntologyId: string,
    importedOntologyName: string,
  ) => void | Promise<void>;

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
  /** Display name of the open ontology — used by canvas menu actions that
   *  seed overlay state (schema diff, revisions inbox, etc.). */
  selectedOntologyName?: string | null;
}
