"""Ontology API package.

Historically a single ~3.6k-line module; split into cohesive sub-routers
(Stream 14 CQ.3). The public surface is unchanged: ``app.api.ontology.router``
mounts every endpoint under ``/api/v1/ontology`` in the original registration
order, so route precedence (static paths before ``/{ontology_id}`` captures)
is preserved exactly.

``asyncio``, ``export_svc`` and ``schema_diff_svc`` are re-exported here so the
existing ``patch("app.api.ontology.<module>.<attr>")`` test targets keep
resolving to the same singleton module objects the sub-routers use.
"""

import asyncio  # noqa: F401  re-exported for patch("app.api.ontology.asyncio.to_thread")

from fastapi import APIRouter

from app.api.ontology import (
    domain,
    entities_read,
    imports,
    imports_io,
    individuals,
    library,
    mutations,
    requirements,
    schema_relational,
    schema_temporal,
)
from app.services import export as export_svc  # noqa: F401  re-exported for tests
from app.services import schema_diff as schema_diff_svc  # noqa: F401  re-exported for tests

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])

# Mount in original source order to preserve route precedence.
router.include_router(library.router)
router.include_router(domain.router)
router.include_router(entities_read.router)
router.include_router(mutations.router)
router.include_router(imports_io.router)
router.include_router(imports.router)
router.include_router(schema_relational.router)
router.include_router(schema_temporal.router)
router.include_router(requirements.router)
router.include_router(individuals.router)

# Re-export handlers / module-level state that callers (mainly tests) still
# import from the package root, mapped to their new sub-modules.
from app.api.ontology.entities_read import (  # noqa: E402,F401
    _LIVE_EDGE_COLLECTIONS,
    _LIVE_EDGES_AND_PROPS_QUERY_CACHE,
    _LIVE_PROP_COLLECTIONS,
    _build_live_edges_and_props_query,
    _fetch_live_edges_and_properties,
)
from app.api.ontology.imports_io import _import_jobs  # noqa: E402,F401
from app.api.ontology.library import (  # noqa: E402,F401
    _batch_edge_counts_for_ontology_ids,
    approve_constraint_endpoint,
    list_ontology_constraints,
    reject_constraint_endpoint,
    update_constraint_endpoint,
)
from app.api.ontology.mutations import export_ontology_endpoint  # noqa: E402,F401
from app.api.ontology.schema_temporal import diff_schema_ontologies  # noqa: E402,F401
