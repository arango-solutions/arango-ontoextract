"""SHACL shapes importer -- Stream 3 PR 3.

Parses ``sh:NodeShape`` / ``sh:PropertyShape`` from a freshly-imported
rdflib graph and materializes each property-level constraint as one
row in ``ontology_constraints``, using the PR 1 wire shape so the
rule engine and the ``/library/{id}/constraints`` API consume SHACL
rows through the same code path as OWL restrictions and LLM-extracted
constraints.

Design choices (locked):

* **Module placement**: separate from ``arangordf_bridge.py`` because
  the bridge file would otherwise breach the 1500-line cap from
  ``modularity-and-structure.mdc``. The hook into the OWL import
  pipeline is added in the bridge; the parsing + materialization
  logic lives here.
* **One row per (property shape, constraint kind)**: a SHACL property
  shape with ``sh:minCount 1`` AND ``sh:datatype xsd:string`` AND
  ``sh:pattern "..."`` produces three rows. This mirrors PR 1 /
  PR 2's "one restriction per row" rule and lets the rule engine
  group / evaluate constraints uniformly.
* **No NodeShape-only row in v1**: NodeShape metadata (severity, target
  class) is inherited by its property shapes. The shape IRI is kept
  in ``shape_iri`` for traceability. ``sh:closed`` is deferred.
* **Provenance**: rows are stamped ``import_source: "shacl_shape"``
  to distinguish from PR 2's ``"owl_restriction"`` and PR 1's
  ``extraction_run_id``. All three are read identically by downstream
  consumers.
* **Rule-engine compatibility**: the cardinality rule's IN clause
  was widened to include ``sh:minCount`` / ``sh:maxCount`` so an
  OWL ``minCardinality 1`` and a SHACL ``sh:minCount 1`` on the same
  ``(class, property)`` collapse into one bound check (the stricter
  applies naturally because the grouped slot keys are ``min``/``max``,
  not the source vocabulary).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from arango.database import StandardDatabase
from rdflib import RDF, RDFS, BNode, Literal, Namespace, URIRef
from rdflib import Graph as RDFGraph

from app.services.arangordf_bridge import _resolve_class_ids, _resolve_property_ids
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


SH = Namespace("http://www.w3.org/ns/shacl#")
OWL_CLASS = URIRef("http://www.w3.org/2002/07/owl#Class")

# ---------------------------------------------------------------------------
# SHACL → restriction_type mapping
#
# Keys are SHACL predicates from the constraint vocabulary; values are the
# strings stored in ``ontology_constraints.restriction_type``. PR 1's
# ``RestrictionType`` enum (which is for LLM-emitted extractions only)
# is intentionally NOT extended -- the DB field is a plain string and
# downstream consumers (rule engine, API) treat unknown restriction_types
# transparently.
#
# These names use the ``sh:`` prefix verbatim so a query, dashboard, or
# UI element can recover the source vocabulary by inspecting the value
# alone. Compare with OWL: ``minCardinality`` (unprefixed) for OWL,
# ``sh:minCount`` for SHACL -- the rule engine treats them as semantically
# equivalent but they remain distinguishable in storage.
# ---------------------------------------------------------------------------
_CARDINALITY_PREDICATES: dict[URIRef, str] = {
    SH.minCount: "sh:minCount",
    SH.maxCount: "sh:maxCount",
}
_VALUE_PREDICATES: dict[URIRef, str] = {
    SH.datatype: "sh:datatype",
    SH["class"]: "sh:class",  # 'class' is a Python keyword -> bracket access
    SH.hasValue: "sh:hasValue",
    SH.pattern: "sh:pattern",
    SH.nodeKind: "sh:nodeKind",
}
# sh:in is special-cased because its object is an RDF list, not a single node.
_IN_PREDICATE: URIRef = SH["in"]

# Severity vocabulary; default per the SHACL spec is sh:Violation.
_DEFAULT_SEVERITY = "sh:Violation"
_SEVERITY_BY_URI: dict[URIRef, str] = {
    SH.Violation: "sh:Violation",
    SH.Warning: "sh:Warning",
    SH.Info: "sh:Info",
}

# Target predicates we recognise. ``sh:targetClass`` is by far the most
# common; the implicit-class-target case (a shape that is itself an
# rdfs:Class or owl:Class) is handled separately. Everything else is
# warn-and-skip in v1.
_TARGET_PREDICATE_CLASS = SH.targetClass
_DEFERRED_TARGET_PREDICATES: tuple[URIRef, ...] = (
    SH.targetSubjectsOf,
    SH.targetObjectsOf,
    SH.targetNode,
)

# Combinators / qualified shapes / SPARQL constraints -- recognised so
# we can warn-and-skip rather than silently misinterpret them.
_DEFERRED_PROPERTY_SHAPE_PREDICATES: tuple[URIRef, ...] = (
    SH["and"],
    SH["or"],
    SH.xone,
    SH["not"],
    SH.qualifiedValueShape,
    SH.qualifiedMinCount,
    SH.qualifiedMaxCount,
    SH.sparql,
)

_IMPORT_SOURCE_SHACL = "shacl_shape"


# ---------------------------------------------------------------------------
# Pure walker -- zero DB calls, fully testable in isolation
# ---------------------------------------------------------------------------


def _extract_shacl_property_constraints(
    rdf_graph: RDFGraph,
) -> list[dict[str, Any]]:
    """Walk ``rdf_graph`` for SHACL node shapes and emit one constraint
    dict per (target class, property path, SHACL constraint kind).

    Returns a list of dicts with keys:

    * ``class_uri``        the target class the property shape constrains
    * ``property_uri``     the constrained property (only simple URI paths
                           supported in v1)
    * ``restriction_type`` the string stored in
                           ``ontology_constraints.restriction_type``,
                           e.g. ``"sh:minCount"``, ``"sh:datatype"``
    * ``restriction_value`` int for counts, str for datatype/class/URI,
                           ``list[str]`` for ``sh:in`` enumerations
    * ``severity``         ``"sh:Violation"`` / ``"sh:Warning"`` /
                           ``"sh:Info"`` -- inherited from NodeShape
                           unless overridden on the PropertyShape
    * ``message``          optional human-readable curator message
                           (from ``sh:message``) or empty string
    * ``shape_iri``        IRI of the owning NodeShape (or ``""`` for
                           anonymous shapes) -- kept for traceability

    All recognised-but-unsupported patterns (complex paths, deferred
    target predicates, combinators) are logged as WARNING and skipped.
    Unknown SHACL predicates are NOT logged -- the SHACL vocabulary
    is large and most of it is harmless metadata (sh:name, sh:description,
    sh:order, sh:group, etc.).
    """
    out: list[dict[str, Any]] = []

    for shape_node in _iter_node_shapes(rdf_graph):
        shape_iri = str(shape_node) if isinstance(shape_node, URIRef) else ""
        target_class_uris = _resolve_node_shape_targets(rdf_graph, shape_node)
        if not target_class_uris:
            # Either uses a deferred target predicate (already warned by
            # _resolve_node_shape_targets) or has no target at all.
            continue

        # Severity declared on the node shape becomes the default for
        # every property shape it contains. SHACL spec: PropertyShape
        # may override.
        node_severity = _read_severity(rdf_graph, shape_node)

        # Walk every sh:property blank node attached to this shape.
        # rdflib's ``objects()`` is typed ``Iterable[Node]`` -- narrow
        # to ``URIRef | BNode`` here because a Literal value of
        # sh:property is malformed SHACL and we'd never see it in
        # practice; skipping defensively keeps mypy honest.
        for raw_property_shape in rdf_graph.objects(shape_node, SH.property):
            if not isinstance(raw_property_shape, (URIRef, BNode)):
                continue
            property_shape: URIRef | BNode = raw_property_shape
            property_uri = _resolve_simple_path(rdf_graph, property_shape, shape_iri)
            if property_uri is None:
                # Complex path or missing path -- warning already emitted.
                continue

            # Refuse to half-import a shape that combines simple constraints
            # with a deferred construct -- the curator should know that
            # part of the shape is being skipped.
            if _has_deferred_constructs(rdf_graph, property_shape, shape_iri, property_uri):
                continue

            # Severity precedence: PropertyShape override > NodeShape > spec default.
            # Returning the resolved value here (rather than ``""`` for "absent")
            # makes the walker's output self-describing -- the materializer
            # doesn't have to know SHACL semantics to fill in the default.
            ps_severity = (
                _read_severity(rdf_graph, property_shape) or node_severity or _DEFAULT_SEVERITY
            )
            message = _read_first_literal(rdf_graph, property_shape, SH.message)

            shape_rows = _interpret_property_shape_constraints(
                rdf_graph,
                property_shape=property_shape,
                shape_iri=shape_iri,
                property_uri=property_uri,
            )
            if not shape_rows:
                # A property shape with only a path and no constraints is
                # legal SHACL (it asserts the path exists in the schema)
                # but produces no rows -- nothing to evaluate.
                continue

            for raw in shape_rows:
                for target_class_uri in target_class_uris:
                    out.append(
                        {
                            "class_uri": target_class_uri,
                            "property_uri": property_uri,
                            "restriction_type": raw["restriction_type"],
                            "restriction_value": raw["restriction_value"],
                            "severity": ps_severity,
                            "message": message,
                            "shape_iri": shape_iri,
                        }
                    )

    return out


def _iter_node_shapes(rdf_graph: RDFGraph) -> list[URIRef | BNode]:
    """Find every node shape in the graph.

    A node shape is any subject that is *either*:

    * explicitly typed ``sh:NodeShape``, OR
    * the subject of a target predicate (``sh:targetClass``, etc.)
      -- many real-world SHACL files omit the type triple

    Anonymous (blank-node) shapes are included so that inline shapes
    inside ``sh:and`` / ``sh:or`` lists are at least skipped with
    intent (those lists are handled by ``_has_deferred_constructs``).

    rdflib's ``subjects()`` returns ``Iterable[Node]`` (Literal is
    structurally possible but never a legal shape subject); we narrow
    explicitly so downstream functions can take ``URIRef | BNode``.
    """
    candidates: set[URIRef | BNode] = set()

    def _collect(triples_iter: Any) -> None:
        for s in triples_iter:
            if isinstance(s, (URIRef, BNode)):
                candidates.add(s)

    _collect(rdf_graph.subjects(RDF.type, SH.NodeShape))
    _collect(rdf_graph.subjects(SH.targetClass, None))
    # The implicit-target predicates below are listed for diagnostics
    # only -- shapes using ONLY them will be discovered here and then
    # warn-skipped by _resolve_node_shape_targets.
    for pred in _DEFERRED_TARGET_PREDICATES:
        _collect(rdf_graph.subjects(pred, None))

    # Deterministic order so tests are stable across rdflib versions.
    return sorted(
        candidates,
        key=lambda n: (1 if isinstance(n, BNode) else 0, str(n)),
    )


def _resolve_node_shape_targets(
    rdf_graph: RDFGraph,
    shape_node: URIRef | BNode,
) -> list[str]:
    """Return the list of class URIs this shape targets.

    Supported in v1:
    * ``sh:targetClass :Foo``
    * Implicit class target -- the shape is itself typed ``rdfs:Class``
      or ``owl:Class``

    Deferred (warn-skip): ``sh:targetSubjectsOf``, ``sh:targetObjectsOf``,
    ``sh:targetNode``. These require either a separate evaluator pass
    or instance-level data that doesn't apply to ontology-level
    cardinality checking.
    """
    target_class_uris: list[str] = []

    for target in rdf_graph.objects(shape_node, _TARGET_PREDICATE_CLASS):
        if isinstance(target, URIRef):
            target_class_uris.append(str(target))

    # Implicit class target: a shape that is itself a class IS its
    # own target. Useful pattern in compact schemas.
    if isinstance(shape_node, URIRef):
        type_set = set(rdf_graph.objects(shape_node, RDF.type))
        if (RDFS.Class in type_set) or (OWL_CLASS in type_set):
            uri = str(shape_node)
            if uri not in target_class_uris:
                target_class_uris.append(uri)

    if target_class_uris:
        return target_class_uris

    # Warn-and-skip if the shape uses a deferred target predicate but
    # nothing supported. Filter to nodes that have *some* target so we
    # don't spam warnings for the shapes-as-mixins case (a shape that
    # is referenced from another shape but has no target of its own).
    for pred in _DEFERRED_TARGET_PREDICATES:
        if (shape_node, pred, None) in rdf_graph:
            log.warning(
                "SHACL shape %s uses %s which is not supported in v1; skipping",
                shape_node,
                pred,
            )
            return []

    # Anonymous shape with no target and no implicit class -- it's
    # almost certainly an inline shape from a combinator or
    # qualified-value-shape construct, which is handled (and warned)
    # elsewhere. Silently skip.
    return []


def _resolve_simple_path(
    rdf_graph: RDFGraph,
    property_shape: URIRef | BNode,
    shape_iri: str,
) -> str | None:
    """Return the URI of a simple ``sh:path`` or ``None``.

    SHACL property paths can be sequences, inverses, alternatives,
    zero-or-more, etc. (those are blank-node expressions). In v1 we
    only handle the single-URI case which covers >90% of real shapes.
    Anything else is warn-skipped.
    """
    path = rdf_graph.value(property_shape, SH.path)
    if path is None:
        log.warning(
            "SHACL PropertyShape on shape %s has no sh:path; skipping",
            shape_iri or property_shape,
        )
        return None
    if not isinstance(path, URIRef):
        log.warning(
            "SHACL PropertyShape on shape %s uses a complex sh:path (%r); "
            "complex property paths are deferred -- skipping",
            shape_iri or property_shape,
            path,
        )
        return None
    return str(path)


def _has_deferred_constructs(
    rdf_graph: RDFGraph,
    property_shape: URIRef | BNode,
    shape_iri: str,
    property_uri: str,
) -> bool:
    """Return True (and log) if this PropertyShape uses a construct we
    don't yet support. Caller skips the whole shape -- partial-import
    risks misrepresenting the schema."""
    for pred in _DEFERRED_PROPERTY_SHAPE_PREDICATES:
        if (property_shape, pred, None) in rdf_graph:
            log.warning(
                "SHACL PropertyShape on shape %s property %s uses %s; "
                "combinators / qualified shapes / sparql are deferred -- "
                "skipping the whole shape so the curator notices",
                shape_iri or property_shape,
                property_uri,
                pred,
            )
            return True
    return False


def _read_severity(
    rdf_graph: RDFGraph,
    node: URIRef | BNode,
) -> str:
    """Read ``sh:severity``; return ``""`` if absent (caller decides
    inheritance vs default)."""
    sev = rdf_graph.value(node, SH.severity)
    if isinstance(sev, URIRef):
        mapped = _SEVERITY_BY_URI.get(sev)
        if mapped is not None:
            return mapped
        # Custom severity URI -- store the full URI string so the UI
        # can render an unknown level intelligibly.
        return str(sev)
    return ""


def _read_first_literal(
    rdf_graph: RDFGraph,
    node: URIRef | BNode,
    predicate: URIRef,
) -> str:
    """Return the lexical form of the first literal value, or ``""``.

    SHACL ``sh:message`` may have language tags; v1 ignores language
    and picks the first literal in rdflib's iteration order.
    """
    for obj in rdf_graph.objects(node, predicate):
        if isinstance(obj, Literal):
            return str(obj)
    return ""


def _interpret_property_shape_constraints(
    rdf_graph: RDFGraph,
    *,
    property_shape: URIRef | BNode,
    shape_iri: str,
    property_uri: str,
) -> list[dict[str, Any]]:
    """Identify every supported SHACL constraint on a property shape.

    Each constraint produces one row dict with ``restriction_type``
    and ``restriction_value``. ``sh:in`` is special-cased because its
    value is an RDF list.
    """
    rows: list[dict[str, Any]] = []

    for pred, rtype in _CARDINALITY_PREDICATES.items():
        raw = rdf_graph.value(property_shape, pred)
        if raw is None:
            continue
        ivalue = _coerce_count_int(raw)
        if ivalue is None:
            log.warning(
                "SHACL %s on shape %s property %s has non-integer value %r; skipping",
                rtype,
                shape_iri or property_shape,
                property_uri,
                raw,
            )
            continue
        rows.append({"restriction_type": rtype, "restriction_value": ivalue})

    for pred, rtype in _VALUE_PREDICATES.items():
        raw = rdf_graph.value(property_shape, pred)
        if raw is None:
            continue
        if isinstance(raw, (URIRef, Literal)):
            # URI for sh:datatype / sh:class / sh:nodeKind; literal-or-URI
            # for sh:hasValue. The rule engine + UI disambiguate by
            # ``restriction_type``.
            rows.append({"restriction_type": rtype, "restriction_value": str(raw)})
        else:
            # Blank-node value of a non-list constraint -- e.g. a
            # nested shape expression. Skip with warning.
            log.warning(
                "SHACL %s on shape %s property %s points at a blank node (%r); "
                "nested shape expressions are not yet supported -- skipping",
                rtype,
                shape_iri or property_shape,
                property_uri,
                raw,
            )

    # sh:in -- value is an RDF list of allowed values.
    in_list_head = rdf_graph.value(property_shape, _IN_PREDICATE)
    if in_list_head is not None and isinstance(in_list_head, (URIRef, BNode, Literal)):
        items = _read_rdf_list(rdf_graph, in_list_head)
        if items is None:
            log.warning(
                "SHACL sh:in on shape %s property %s is not a well-formed RDF list; skipping",
                shape_iri or property_shape,
                property_uri,
            )
        elif not items:
            log.warning(
                "SHACL sh:in on shape %s property %s is empty; skipping",
                shape_iri or property_shape,
                property_uri,
            )
        else:
            rows.append({"restriction_type": "sh:in", "restriction_value": items})

    return rows


def _read_rdf_list(
    rdf_graph: RDFGraph,
    list_head: URIRef | BNode | Literal,
) -> list[str] | None:
    """Walk an RDF list and return string values, or ``None`` if malformed.

    Each list item must be a URI or literal; nested list items (a list
    of lists) are not supported and return ``None`` to signal the
    caller to skip with a warning.
    """
    if not isinstance(list_head, (URIRef, BNode)):
        return None
    out: list[str] = []
    try:
        for item in rdf_graph.items(list_head):
            if isinstance(item, (URIRef, Literal)):
                out.append(str(item))
            else:
                return None
    except Exception:
        # rdflib raises various errors on malformed lists; treat all
        # as "skip with warning" rather than crashing the import.
        log.debug("rdf list walk failed", exc_info=True)
        return None
    return out


def _coerce_count_int(raw: Any) -> int | None:
    """Coerce an rdflib literal to a non-negative int, or ``None``.

    Mirrors PR 2's ``_coerce_cardinality_int`` but is duplicated here
    because the SHACL importer should be standalone -- the bridge file
    may change its private helpers in future without breaking SHACL.
    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if raw >= 0 else None
    if isinstance(raw, Literal):
        try:
            value = raw.toPython()
        except Exception:
            value = None
        if isinstance(value, int) and not isinstance(value, bool):
            return value if value >= 0 else None
        lex = str(raw).strip()
        if lex.isdigit():
            return int(lex)
    return None


# ---------------------------------------------------------------------------
# DB-aware orchestrator
# ---------------------------------------------------------------------------


def import_shacl_shapes(
    db: StandardDatabase,
    *,
    rdf_graph: RDFGraph,
    ontology_id: str,
    now: float | None = None,
) -> int:
    """Materialise SHACL shapes from ``rdf_graph`` into ``ontology_constraints``.

    Resolves each row's ``class_uri`` to a live class id and each
    ``property_uri`` to a live property id (object or datatype), then
    writes the constraint in the PR 1 wire shape plus a SHACL
    provenance marker.

    Returns the count of rows successfully written.

    Failure modes (all non-fatal):

    * Class URI not in this ontology -> skip row + warn
      (the rule engine joins on ``on_class``; orphan rows can't fire)
    * Property URI not resolvable     -> persist with ``property_id=null``
      (mirrors PR 1 / PR 2 resolver-miss path)
    * Insert fails (e.g. unique violation) -> log + continue
    """
    raw_rows = _extract_shacl_property_constraints(rdf_graph)
    if not raw_rows:
        return 0

    if not db.has_collection("ontology_constraints"):
        db.create_collection("ontology_constraints")

    if now is None:
        now = time.time()

    class_id_map = _resolve_class_ids(
        db,
        ontology_id=ontology_id,
        class_uris=sorted({r["class_uri"] for r in raw_rows}),
    )
    property_id_map = _resolve_property_ids(
        db,
        ontology_id=ontology_id,
        property_uris=sorted({r["property_uri"] for r in raw_rows}),
    )

    constraint_col = db.collection("ontology_constraints")
    written = 0
    skipped_no_class = 0
    skipped_no_property = 0

    for row in raw_rows:
        class_uri = row["class_uri"]
        property_uri = row["property_uri"]
        class_id = class_id_map.get(class_uri)
        if class_id is None:
            log.warning(
                "SHACL constraint targets class %s which is not in ontology %s "
                "after import; skipping constraint for property %s",
                class_uri,
                ontology_id,
                property_uri,
            )
            skipped_no_class += 1
            continue

        property_id = property_id_map.get(property_uri)
        if property_id is None:
            skipped_no_property += 1
            log.warning(
                "SHACL constraint on class %s references property %s which is not "
                "in ontology %s after import; persisting with property_id=null "
                "so post-hoc repair can recover the link",
                class_uri,
                property_uri,
                ontology_id,
            )

        description = row["message"] or (
            f"Imported from SHACL shape {row['shape_iri']}"
            if row["shape_iri"]
            else "Imported from SHACL (anonymous shape)"
        )

        constraint_doc: dict[str, Any] = {
            "constraint_type": "sh:PropertyShape",
            "on_class": class_id,
            "property_id": property_id,
            "property_uri": property_uri,
            "restriction_type": row["restriction_type"],
            "restriction_value": row["restriction_value"],
            "description": description,
            "ontology_id": ontology_id,
            "import_source": _IMPORT_SOURCE_SHACL,
            "severity": row["severity"] or _DEFAULT_SEVERITY,
            "shape_iri": row["shape_iri"],
            # Imported SHACL axioms are explicit -- treat as ground truth.
            "confidence": 1.0,
            "evidence": [],
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            constraint_col.insert(constraint_doc)
            written += 1
        except Exception as exc:
            log.warning(
                "SHACL constraint insert failed for class %s property %s restriction_type %s: %s",
                class_uri,
                property_uri,
                row["restriction_type"],
                exc,
            )

    log.info(
        "shacl shapes imported",
        extra={
            "ontology_id": ontology_id,
            "written": written,
            "skipped_no_class": skipped_no_class,
            "skipped_no_property_resolution": skipped_no_property,
            "total_candidates": len(raw_rows),
        },
    )
    return written
