"""Regression tests for the assembled ontology router (Stream 14 CQ.3).

The ontology API was split from one ~3.6k-line module into cohesive
sub-routers mounted by ``app.api.ontology.__init__``. Two properties must
survive that split and any future re-ordering of ``include_router`` calls:

1. No endpoint is silently dropped (the public surface is stable).
2. A dynamic ``/{ontology_id}/...`` route never shadows a more specific
   literal-prefixed route registered after it -- the exact failure the
   original module guarded against with a hand-placed "static routes first"
   comment (e.g. ``/domain/classes`` vs ``/{ontology_id}/classes``).

Why introspect via OpenAPI rather than ``router.routes``
--------------------------------------------------------
FastAPI >= 0.139 no longer eagerly flattens an included sub-router's routes
into the parent ``APIRouter.routes`` list. Each ``include_router`` call is
stored as a lazy ``fastapi.routing._IncludedRouter`` placeholder that resolves
its children at request time (the ``effective_candidates`` machinery), and the
parent prefix is applied then too. As a result ``router.routes`` reads back as
seven opaque placeholders with no ``.path``/``.methods`` -- an earlier version
of this test read them directly and silently saw *zero* routes on CI while
passing locally against an older FastAPI.

The OpenAPI schema of an app that mounts the router is the public,
version-stable projection of the real routing surface, so we assert against
that instead. Its ``paths`` mapping preserves registration order, which keeps
the shadow-ordering check (property 2) meaningful.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.ontology import router as ontology_router

# Canonical mount point and the count of (path, method) pairs exposed beneath
# it. Pinned so an accidental drop/duplication during a future refactor fails
# loudly.
ONTOLOGY_PREFIX = "/api/v1/ontology"
# 61 + 4 requirements/coverage (Stream 22 CQ-PR1/4/5) + 2 individuals
# (Stream 21 AB-PR6) + 1 requirements/formalize (Stream 22 CQ-PR3)
# + 1 individuals/canonicalize (Stream 21 AB-PR3)
# + 1 individuals/validate (Stream 21 AB-PR5) = 70.
EXPECTED_ROUTE_COUNT = 70


def _ontology_openapi_paths() -> dict[str, list[str]]:
    """Return ``{path: [UPPERCASE methods]}`` for every ontology endpoint.

    Builds a throwaway app so the router's lazy sub-routers are resolved and
    projected into a stable, public OpenAPI view.
    """
    app = FastAPI()
    app.include_router(ontology_router)
    return {
        path: sorted(method.upper() for method in operations)
        for path, operations in app.openapi().get("paths", {}).items()
        if path.startswith(ONTOLOGY_PREFIX)
    }


def _route_pairs(paths: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(path, method) for path, methods in paths.items() for method in methods]


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _is_var(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def test_route_count_is_stable() -> None:
    assert len(_route_pairs(_ontology_openapi_paths())) == EXPECTED_ROUTE_COUNT


def test_router_mounts_under_canonical_prefix() -> None:
    assert ontology_router.prefix == ONTOLOGY_PREFIX
    paths = set(_ontology_openapi_paths())
    # A representative endpoint from each sub-router must be present.
    for expected in (
        "/api/v1/ontology/library",
        "/api/v1/ontology/domain/classes",
        "/api/v1/ontology/{ontology_id}/classes",
        "/api/v1/ontology/{ontology_id}/classes/{class_key}",
        "/api/v1/ontology/import",
        "/api/v1/ontology/{ontology_id}/imports",
        "/api/v1/ontology/catalog",
        "/api/v1/ontology/schema/extract",
        "/api/v1/ontology/schema/relational/tables",
        "/api/v1/ontology/schema/relational/extract",
    ):
        assert expected in paths, f"missing endpoint {expected}"


def _shadows(general: list[str], specific: list[str]) -> bool:
    """True if ``general`` matches every concrete path ``specific`` does and is
    strictly more general (has a path variable where ``specific`` has a literal).
    """
    if len(general) != len(specific):
        return False
    strictly_more_general = False
    for g, s in zip(general, specific, strict=True):
        g_var, s_var = _is_var(g), _is_var(s)
        if g_var and not s_var:
            strictly_more_general = True
        elif not g_var and not s_var:
            if g != s:
                return False
        elif not g_var and s_var:
            # specific is the more general one here -> wrong direction
            return False
        # both vars: compatible, contributes nothing
    return strictly_more_general


def test_static_routes_register_before_shadowing_dynamic_routes() -> None:
    paths = _ontology_openapi_paths()
    # OpenAPI ``paths`` preserves registration order, so index position is a
    # faithful proxy for "which route FastAPI considers first".
    ordered = list(paths)
    for i, general_path in enumerate(ordered):
        gsegs = _segments(general_path)
        general_methods = set(paths[general_path])
        for j, specific_path in enumerate(ordered):
            if i == j or general_methods.isdisjoint(paths[specific_path]):
                continue
            if _shadows(gsegs, _segments(specific_path)):
                assert j < i, (
                    f"route '{specific_path}' is shadowed by the more general "
                    f"'{general_path}' registered before it; mount the sub-router "
                    f"with the specific/static route earlier in __init__"
                )
