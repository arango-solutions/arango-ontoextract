"""Shared database utilities used across repository modules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def run_aql(
    db: StandardDatabase,
    query: str,
    bind_vars: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Cursor:
    """Execute an AQL query and return a Cursor.

    python-arango types ``aql.execute`` as returning
    ``Cursor | AsyncJob | BatchJob | None`` but in synchronous mode
    it always returns ``Cursor``.  This wrapper narrows the type so
    callers don't need ``cast()`` at every call-site.
    """
    result = db.aql.execute(query, bind_vars=bind_vars, **kwargs)
    return cast(Cursor, result)


def doc_get(collection: Any, key: str) -> dict[str, Any] | None:
    """Get a document by key, returning a typed dict or None.

    python-arango types ``collection.get`` as returning
    ``dict | AsyncJob | BatchJob | None``.  In synchronous mode it
    always returns ``dict | None``.
    """
    result = collection.get(key)
    return cast("dict[str, Any] | None", result)
