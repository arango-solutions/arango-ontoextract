"""Shared, patch-friendly dependency handles for the ontology API package.

Sub-modules reference these via attribute access (``_shared.get_db(...)``,
``_shared.run_aql(...)``, ``_shared.ontology_repo.<fn>``) so a single
``patch("app.api.ontology._shared.<name>")`` in tests rebinds the dependency
for every sub-router at once -- the binding lives in exactly one place.
"""

from app.db import constraints_repo, ontology_repo, registry_repo
from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import run_aql
from app.services.arangordf_bridge import import_from_file

__all__ = [
    "constraints_repo",
    "get_db",
    "import_from_file",
    "ontology_repo",
    "paginate",
    "registry_repo",
    "run_aql",
]
