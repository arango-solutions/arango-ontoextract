"""Cursor-based pagination for AQL queries.

Cursors are base64-encoded sort keys. The helper builds AQL filter/sort/limit
clauses and wraps results in PaginatedResponse.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, TypeVar

from arango.database import StandardDatabase

from app.db.utils import run_aql
from app.models.common import PaginatedResponse

log = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


def encode_cursor(sort_value: Any, key: str) -> str:
    """Encode a (sort_value, _key) pair into an opaque cursor string."""
    payload = json.dumps({"v": sort_value, "k": key}, default=str)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[Any, str]:
    """Decode a cursor into (sort_value, _key)."""
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return payload["v"], payload["k"]


def paginate(
    db: StandardDatabase,
    *,
    collection: str,
    sort_field: str = "_key",
    sort_order: str = "asc",
    limit: int = _DEFAULT_LIMIT,
    cursor: str | None = None,
    filters: dict[str, Any] | None = None,
    extra_aql: str = "",
    bind_vars: dict[str, Any] | None = None,
) -> PaginatedResponse[dict]:
    """Execute a paginated AQL query on a collection.

    Parameters
    ----------
    db:
        ArangoDB database handle.
    collection:
        Name of the collection to query.
    sort_field:
        Field to sort/paginate on (must be indexed for performance).
    sort_order:
        ``"asc"`` or ``"desc"``.
    limit:
        Page size (clamped to ``_MAX_LIMIT``).
    cursor:
        Opaque cursor from a previous response.
    filters:
        Simple equality filters ``{field: value}``.
    extra_aql:
        Additional AQL FILTER clause injected after the standard filters.
        Must reference the loop variable ``doc``.
    bind_vars:
        Extra bind variables for ``extra_aql``.
    """
    limit = min(max(1, limit), _MAX_LIMIT)
    ascending = sort_order.lower() != "desc"

    bv: dict[str, Any] = {
        "@col": collection,
        "lim": limit + 1,
    }
    if bind_vars:
        bv.update(bind_vars)

    filter_lines: list[str] = []
    if filters:
        for i, (field, value) in enumerate(filters.items()):
            var = f"fv{i}"
            filter_lines.append(f"FILTER doc.`{field}` == @{var}")
            bv[var] = value

    if cursor:
        cursor_val, cursor_key = decode_cursor(cursor)
        bv["cursor_val"] = cursor_val
        bv["cursor_key"] = cursor_key
        op = ">" if ascending else "<"
        filter_lines.append(
            f"FILTER (doc.`{sort_field}` {op} @cursor_val"
            f" OR (doc.`{sort_field}` == @cursor_val AND doc._key {op} @cursor_key))"
        )

    direction = "ASC" if ascending else "DESC"
    filter_block = "\n  ".join(filter_lines)
    extra = f"\n  {extra_aql}" if extra_aql else ""

    query = f"""\
FOR doc IN @@col
  {filter_block}{extra}
  SORT doc.`{sort_field}` {direction}, doc._key {direction}
  LIMIT @lim
  RETURN doc"""

    count_query = f"""\
FOR doc IN @@col
  {filter_block}{extra}
  COLLECT WITH COUNT INTO c
  RETURN c"""

    rows = list(run_aql(db, query, bind_vars=bv))
    count_bv = {k: v for k, v in bv.items() if k not in ("lim",)}
    total_count = next(iter(run_aql(db, count_query, bind_vars=count_bv)))

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.get(sort_field), last["_key"])

    return PaginatedResponse(
        data=rows,
        cursor=next_cursor,
        has_more=has_more,
        total_count=total_count,
    )
