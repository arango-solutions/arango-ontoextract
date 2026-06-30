"""Regression tests for the assembled ontology router (Stream 14 CQ.3).

The ontology API was split from one ~3.6k-line module into cohesive
sub-routers mounted by ``app.api.ontology.__init__``. Two properties must
survive that split and any future re-ordering of ``include_router`` calls:

1. No endpoint is silently dropped (the public surface is stable).
2. A dynamic ``/{ontology_id}/...`` route never shadows a more specific
   literal-prefixed route registered after it -- the exact failure the
   original module guarded against with a hand-placed "static routes first"
   comment (e.g. ``/domain/classes`` vs ``/{ontology_id}/classes``).
"""

from __future__ import annotations

from app.api.ontology import router

# Pinned so an accidental drop/duplication during a future refactor fails loudly.
EXPECTED_ROUTE_COUNT = 59


def _ordered_routes() -> list[tuple[str, frozenset[str]]]:
    routes: list[tuple[str, frozenset[str]]] = []
    for r in router.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path is None or methods is None:
            continue
        routes.append((path, frozenset(methods)))
    return routes


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _is_var(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def test_route_count_is_stable() -> None:
    assert len(_ordered_routes()) == EXPECTED_ROUTE_COUNT


def test_router_mounts_under_canonical_prefix() -> None:
    assert router.prefix == "/api/v1/ontology"
    paths = {p for p, _ in _ordered_routes()}
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
    routes = _ordered_routes()
    for i, (general_path, general_methods) in enumerate(routes):
        gsegs = _segments(general_path)
        for j, (specific_path, specific_methods) in enumerate(routes):
            if i == j or general_methods.isdisjoint(specific_methods):
                continue
            if _shadows(gsegs, _segments(specific_path)):
                assert j < i, (
                    f"route '{specific_path}' is shadowed by the more general "
                    f"'{general_path}' registered before it; mount the sub-router "
                    f"with the specific/static route earlier in __init__"
                )
