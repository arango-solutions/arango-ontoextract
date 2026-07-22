"""Domain ontology context serialization for Tier 2 extraction.

Serializes domain ontology class hierarchy into compact text for LLM prompt
injection, enabling context-aware extraction that classifies entities as
EXISTING, EXTENSION, or NEW relative to the domain.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


def serialize_domain_context(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> str:
    """Query domain ontology classes + hierarchy, serialize as compact text.

    Format::

        Domain: <ontology_name>
        Classes:
        - ParentClass
          - ChildClass (props: p1, p2)
          - ChildClass2
        ...

    Only current (non-expired) classes and edges are included.
    """
    if db is None:
        db = get_db()

    ontology_name = _get_ontology_name(db, ontology_id)
    classes = _get_current_classes(db, ontology_id)
    hierarchy = _get_subclass_edges(db, ontology_id)

    if not classes:
        return f"Domain: {ontology_name}\nClasses: (none)"

    class_by_id: dict[str, dict[str, Any]] = {c["_id"]: c for c in classes}
    class_ids = list(class_by_id.keys())
    children_map: dict[str, list[str]] = {}
    child_ids: set[str] = set()

    for edge in hierarchy:
        parent_id = edge.get("_to", "")
        child_id = edge.get("_from", "")
        if parent_id in class_by_id and child_id in class_by_id:
            children_map.setdefault(parent_id, []).append(child_id)
            child_ids.add(child_id)

    rdfs_labels = (
        _property_labels_from_rdfs_domain(db, ontology_id, class_ids)
        if class_ids and db.has_collection("rdfs_domain")
        else {}
    )
    legacy_labels: dict[str, list[str]] = {}
    if db.has_collection("ontology_properties"):
        legacy_labels = _legacy_property_labels_by_class(
            _get_class_properties(db, ontology_id),
            class_by_id,
        )

    props_map: dict[str, list[str]] = {}
    for cid in class_ids:
        merged: list[str] = []
        merged.extend(rdfs_labels.get(cid, []))
        merged.extend(legacy_labels.get(cid, []))
        seen: set[str] = set()
        uniq: list[str] = []
        for label in merged:
            if label and label not in seen:
                seen.add(label)
                uniq.append(label)
        if uniq:
            props_map[cid] = uniq

    root_ids = [cid for cid in class_by_id if cid not in child_ids]
    root_ids.sort(key=lambda cid: class_by_id[cid].get("label", ""))

    lines = [f"Domain: {ontology_name}", "Classes:"]

    def _render_tree(class_id: str, depth: int) -> None:
        cls = class_by_id[class_id]
        label = cls.get("label", cls.get("uri", "unknown"))
        prop_names = props_map.get(class_id, [])
        suffix = f" (props: {', '.join(prop_names)})" if prop_names else ""
        indent = "  " * depth
        lines.append(f"{indent}- {label}{suffix}")

        for child_id in sorted(
            children_map.get(class_id, []),
            key=lambda cid: class_by_id[cid].get("label", ""),
        ):
            _render_tree(child_id, depth + 1)

    for root_id in root_ids:
        _render_tree(root_id, 0)

    return "\n".join(lines)


def get_domain_ontology_for_org(
    db: StandardDatabase | None = None,
    *,
    org_id: str,
) -> list[str]:
    """Return ontology_ids selected by an organization.

    Reads from the ``organizations`` collection's ``selected_ontologies`` field.
    Falls back to an empty list if the org or field doesn't exist.
    """
    if db is None:
        db = get_db()

    if not db.has_collection("organizations"):
        return []

    query = """\
FOR org IN organizations
  FILTER org._key == @org_id
  LIMIT 1
  RETURN org.selected_ontologies"""

    results = list(run_aql(db, query, bind_vars={"org_id": org_id}))
    if not results or results[0] is None:
        return []
    return list(results[0])


def set_domain_ontology_for_org(
    db: StandardDatabase | None = None,
    *,
    org_id: str,
    ontology_ids: list[str],
) -> dict[str, Any]:
    """Update the selected base ontologies for an organization.

    Validates that all referenced ontology_ids exist in the registry.
    Returns the updated organization document.
    """
    if db is None:
        db = get_db()

    if db.has_collection("ontology_registry"):
        for oid in ontology_ids:
            exists = list(
                run_aql(
                    db,
                    "FOR r IN ontology_registry FILTER r._key == @k LIMIT 1 RETURN 1",
                    bind_vars={"k": oid},
                )
            )
            if not exists:
                raise ValueError(f"Ontology '{oid}' not found in registry")

    if not db.has_collection("organizations"):
        db.create_collection("organizations")

    existing = list(
        run_aql(
            db,
            "FOR org IN organizations FILTER org._key == @k LIMIT 1 RETURN org",
            bind_vars={"k": org_id},
        )
    )
    if existing:
        result = cast(
            "dict[str, Any]",
            db.collection("organizations").update(
                {"_key": org_id, "selected_ontologies": ontology_ids},
                return_new=True,
            ),
        )
        return cast(dict[str, Any], result["new"])

    result = cast(
        "dict[str, Any]",
        db.collection("organizations").insert(
            {"_key": org_id, "selected_ontologies": ontology_ids},
            return_new=True,
        ),
    )
    return cast(dict[str, Any], result["new"])


def serialize_multi_domain_context(
    db: StandardDatabase | None = None,
    *,
    ontology_ids: list[str],
) -> str:
    """Serialize context from multiple domain ontologies for Tier 2 prompts."""
    if db is None:
        db = get_db()

    if not ontology_ids:
        return ""

    parts: list[str] = []
    for oid in ontology_ids:
        ctx = serialize_domain_context(db, ontology_id=oid)
        parts.append(ctx)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Stream 22: use-case / competency-question scope injection (FR-19.4, FR-19.7)
# ---------------------------------------------------------------------------

# Marker substring the extractor / tests / ops grep for to confirm the CQ-scope
# block was injected. Changing it is a semver-style break (prompt-leak audits).
CQ_SCOPE_CONTEXT_HEADER = (
    "Use-case scope (prioritize concepts and relationships needed to answer "
    "these competency questions):"
)

# Priority tokens -> sort rank (lower sorts first). Unknown priorities sort last
# but keep their spec order (stable sort).
_PRIORITY_RANK = {
    "p1": 0,
    "high": 0,
    "must": 0,
    "p2": 1,
    "medium": 1,
    "should": 1,
    "p3": 2,
    "low": 2,
    "could": 2,
}


def _cq_priority_rank(cq: dict[str, Any]) -> int:
    raw = cq.get("priority")
    if isinstance(raw, int):
        return raw
    return _PRIORITY_RANK.get(str(raw or "").strip().lower(), 99)


def serialize_cq_scope_context(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> str:
    """Serialize an ontology's competency-question scope as extraction context.

    CQ scope injection (Stream 22, FR-19.4 / FR-19.7): reads the ORSD-style
    requirements spec attached to ``ontology_id`` and renders its use cases +
    competency questions (priority-ordered) as a prompt block that tells the
    extractor which concepts and relationships to prioritize so the resulting
    ontology can actually answer the questions the user cares about.

    Returns ``""`` when there is no spec or no competency questions, so an
    extraction with no requirements is byte-identical to before.
    """
    if db is None:
        db = get_db()

    # Local import to avoid a module-load cycle (requirements_repo -> db utils).
    from app.db import requirements_repo

    spec = requirements_repo.get_requirements(db, ontology_id)
    if not spec:
        return ""
    cqs = requirements_repo.iter_competency_questions(spec)
    if not cqs:
        return ""

    lines: list[str] = [CQ_SCOPE_CONTEXT_HEADER, ""]
    purpose = str(spec.get("purpose") or "").strip()
    if purpose:
        lines.append(f"Purpose: {purpose}")
    scope = str(spec.get("scope") or "").strip()
    if scope:
        lines.append(f"Scope: {scope}")
    if purpose or scope:
        lines.append("")

    # Group by use case, preserving spec order; CQs within a group sort by
    # priority. ``dict`` preserves insertion order so the first-seen use case
    # renders first.
    by_uc: dict[str, list[dict[str, Any]]] = {}
    for cq in cqs:
        by_uc.setdefault(str(cq.get("use_case") or "General"), []).append(cq)

    for uc_name, group in by_uc.items():
        lines.append(f"Use case: {uc_name}")
        for cq in sorted(group, key=_cq_priority_rank):
            text = str(cq.get("text") or "").strip()
            if not text:
                continue
            prio = str(cq.get("priority") or "").strip()
            prefix = f"[{prio}] " if prio else ""
            lines.append(f"  - {prefix}{text}")
            shape = str(cq.get("expected_answer_shape") or "").strip()
            if shape:
                lines.append(f"      expected answer: {shape}")
        lines.append("")

    lines.extend(
        [
            "Guidelines:",
            "- Prioritize extracting the classes, properties, and relationships "
            "required to answer the questions above.",
            "- Do NOT omit other salient concepts in the text; this is a priority "
            "signal, not an exclusive whitelist.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# H.17: import-aware extraction context
# ---------------------------------------------------------------------------


# Marker substring the extractor / tests / ops grep for to confirm the H.17
# header was actually injected into the prompt. Changing this string is a
# semver-style break: dashboards and prompt-leak audits look for it.
EFFECTIVE_CONTEXT_HEADER = "Existing ontology context (reuse these classes; do not duplicate):"


def serialize_effective_ontology_context(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    max_depth: int = 10,
) -> str:
    """Serialize the *effective* ontology (own + transitive imports) as
    LLM prompt context for import-aware extraction (Stream 1 H.17).

    The output is grouped by source ontology so the LLM can tell which
    classes it can extend (own) versus which it should only reference
    (imported). The footer spells out the reuse rules explicitly because
    LLM extractors otherwise default to minting fresh URIs even when
    a perfectly good URI exists in the imported closure.

    Format::

        Existing ontology context (reuse these classes; do not duplicate):

        Your ontology (<self_name>):
        - Class [<self_namespace#Class>]
          - SubClass [<self_namespace#SubClass>]
        ...

        Imported from <SourceName> (depth <N>):
        - ImportedClass [<imported_uri>]
          - ImportedSub [<imported_uri>]
        ...

        Guidelines:
        - When the text describes a class above, REUSE its URI.
        - To specialize: set ``parent_uri`` to the existing URI and use
          classification: "extension".
        - To declare equivalence: use the existing URI directly with
          classification: "existing".
        - DO NOT mint new URIs for concepts already present above.

    Parameters
    ----------
    db:
        ArangoDB handle. Defaults to ``get_db()`` so the call site
        matches ``serialize_domain_context``; tests inject a ``MagicMock``.
    ontology_id:
        Registry ``_key`` of the *target* (the ontology being extracted
        into).
    max_depth:
        Forwarded to ``compute_effective_ontology`` (clamped to 1..50).

    Returns
    -------
    str
        Multi-section text, or ``""`` when the target has no classes
        AND no imports. An empty result is intentional: dropping an
        empty header into the prompt would just waste tokens.
    """
    if db is None:
        db = get_db()

    # Local import to break a backward-compatible cycle: ontology_effective
    # is a higher-level service that depends on db utilities; importing
    # it here at the module top would force every consumer of the
    # smaller serialize_domain_context to pay its import cost too.
    from app.services.ontology_effective import compute_effective_ontology

    try:
        effective = compute_effective_ontology(
            db,
            ontology_id=ontology_id,
            include="summary",
            max_depth=max_depth,
        )
    except ValueError:
        # ``ontology_id`` not in registry -- treat as "no context". The
        # extraction service catches this same case via its own log
        # message; we surface it as ``""`` so the prompt is unchanged
        # rather than poisoning the run with an inline error string.
        return ""

    classes = list(effective.get("classes") or [])
    edges = list(effective.get("edges") or [])
    sources = list(effective.get("sources") or [])

    if not classes:
        # Empty target ontology with no imported classes either -- the
        # extraction is doing greenfield work, the prompt should not
        # advertise an empty hierarchy.
        return ""

    self_name = effective.get("ontology_name") or ontology_id

    # Build per-source ``_id -> class`` maps so the renderer can walk
    # each source's tree independently. ``_id`` is the canonical join
    # key on subclass_of edges (``_from`` / ``_to``).
    by_source: dict[str, dict[str, dict[str, Any]]] = {}
    for cls in classes:
        oid = str(cls.get("source_ontology_id") or ontology_id)
        cid = str(cls.get("_id") or "")
        if not cid:
            continue
        by_source.setdefault(oid, {})[cid] = cls

    # Parent map per source -- only subclass_of edges where BOTH ends
    # belong to the same source. Cross-source subclass relationships
    # are flagged as conflicts by H.13; ignoring them here keeps the
    # tree rendering unambiguous (the imported-from header naming the
    # source IS the cross-source relationship, structurally).
    children_by_source: dict[str, dict[str, list[str]]] = {}
    child_ids_by_source: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("edge_type") != "subclass_of":
            continue
        child_id = str(edge.get("_from") or "")
        parent_id = str(edge.get("_to") or "")
        if not child_id or not parent_id:
            continue
        # Place the edge under the parent's source -- the parent is the
        # node we walk DOWN from, so children render correctly.
        for oid, cmap in by_source.items():
            if parent_id in cmap and child_id in cmap:
                children_by_source.setdefault(oid, {}).setdefault(parent_id, []).append(child_id)
                child_ids_by_source.setdefault(oid, set()).add(child_id)
                break

    # Group ``Imported from ...`` sections by source ``_key``. We
    # explicitly normalise None -> ``_key`` here (rather than at the
    # render site) so every downstream lookup gets a non-None string
    # back and the ``.lower()`` sort key cannot blow up.
    source_names: dict[str, str] = {}
    for s in sources:
        key = str(s.get("_key") or "")
        if not key:
            continue
        source_names[key] = str(s.get("name") or key)
    source_depths = {str(s.get("_key") or ""): int(s.get("depth") or 0) for s in sources}

    # Self always renders first (depth 0), then imports in BFS-depth
    # order so the most-related ontology shows up first.
    ordered_oids: list[str] = []
    if ontology_id in by_source:
        ordered_oids.append(ontology_id)

    def _sort_key(o: str) -> tuple[int, str]:
        # Explicit helper rather than an inline lambda so mypy can see
        # the (str) -> (int, str) signature directly. ``source_names``
        # is dict[str, str] by construction above, but mypy was tripping
        # on the inferred return of .get inside a lambda body.
        name = source_names.get(o) or o
        return (source_depths.get(o, 99), name.lower())

    imported_oids = sorted(
        (oid for oid in by_source if oid != ontology_id),
        key=_sort_key,
    )
    ordered_oids.extend(imported_oids)

    lines: list[str] = [EFFECTIVE_CONTEXT_HEADER, ""]

    for oid in ordered_oids:
        cmap = by_source[oid]
        if oid == ontology_id:
            lines.append(f"Your ontology ({self_name}):")
        else:
            src_name = source_names.get(oid) or oid
            depth = source_depths.get(oid, 1)
            lines.append(f"Imported from {src_name} (depth {depth}):")

        children = children_by_source.get(oid, {})
        child_ids = child_ids_by_source.get(oid, set())
        root_ids = sorted(
            (cid for cid in cmap if cid not in child_ids),
            key=lambda c: cmap[c].get("label") or cmap[c].get("uri") or c,
        )

        # Bind cmap / children by default-arg capture so the closure
        # is independent of the surrounding loop variable (mypy is happy
        # with the explicit dict[str, ...] types).
        def _render(
            cid: str,
            depth: int,
            cmap: dict[str, dict[str, Any]] = cmap,
            children: dict[str, list[str]] = children,
        ) -> None:
            cls = cmap[cid]
            label = cls.get("label") or cls.get("uri") or cid
            uri = cls.get("uri")
            uri_suffix = f" [{uri}]" if uri else ""
            indent = "  " * depth
            lines.append(f"{indent}- {label}{uri_suffix}")
            for child in sorted(
                children.get(cid, []),
                key=lambda c: cmap[c].get("label") or cmap[c].get("uri") or c,
            ):
                _render(child, depth + 1)

        for root in root_ids:
            _render(root, 0)

        lines.append("")

    lines.extend(
        [
            "Guidelines:",
            (
                "- When the text describes a class above, REUSE its URI rather "
                "than minting a new one."
            ),
            (
                "- To specialize an existing class: set parent_uri to its URI "
                'and use classification: "extension".'
            ),
            (
                "- To declare semantic equivalence: use the existing URI "
                'directly with classification: "existing".'
            ),
            (
                "- DO NOT mint new URIs for concepts already present above; "
                "the conflict detector will flag duplicates."
            ),
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_ontology_name(db: StandardDatabase, ontology_id: str) -> str:
    if not db.has_collection("ontology_registry"):
        return ontology_id

    results = list(
        run_aql(
            db,
            "FOR r IN ontology_registry FILTER r._key == @k LIMIT 1 RETURN r.name",
            bind_vars={"k": ontology_id},
        )
    )
    return results[0] if results and results[0] else ontology_id


def _get_current_classes(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_classes"):
        return []

    return list(
        run_aql(
            db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN cls""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _get_subclass_edges(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    if not db.has_collection("subclass_of"):
        return []

    return list(
        run_aql(
            db,
            """\
FOR e IN subclass_of
  FILTER e.expired == @never
  RETURN e""",
            bind_vars={"never": NEVER_EXPIRES},
        )
    )


def _get_class_properties(db: StandardDatabase, ontology_id: str) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_properties"):
        return []

    return list(
        run_aql(
            db,
            """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  RETURN prop""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _property_labels_from_rdfs_domain(
    db: StandardDatabase,
    ontology_id: str,
    class_ids: list[str],
) -> dict[str, list[str]]:
    """Map class document id → property labels via PGT ``rdfs_domain`` edges (ADR-006)."""
    if not class_ids:
        return {}

    rows = list(
        run_aql(
            db,
            """\
FOR e IN rdfs_domain
  FILTER e.ontology_id == @oid AND e.expired == @never
  FILTER e._to IN @cids
  LET prop = DOCUMENT(e._from)
  FILTER prop != null AND prop.expired == @never AND prop.ontology_id == @oid
  RETURN { "class_id": e._to, "label": prop.label }""",
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "cids": class_ids,
            },
        )
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        cid = row.get("class_id")
        label = row.get("label")
        if cid and label:
            out.setdefault(cid, []).append(label)
    return out


def _legacy_property_labels_by_class(
    properties: list[dict[str, Any]],
    class_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Build class_id → labels from legacy ``ontology_properties`` documents."""
    out: dict[str, list[str]] = {}
    for prop in properties:
        domain_id = prop.get("domain_class_id")
        if not domain_id and prop.get("domain_class"):
            frag = str(prop["domain_class"]).split("#")[-1].split("/")[-1]
            domain_id = f"ontology_classes/{frag}"
        if not domain_id or domain_id not in class_by_id:
            continue
        label = prop.get("label") or prop.get("uri") or ""
        if label:
            out.setdefault(domain_id, []).append(label)
    return out
