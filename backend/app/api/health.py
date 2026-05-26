from typing import Any

from fastapi import APIRouter

from app.api.metrics import DB_CONNECTION_ERRORS
from app.db.client import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness probe -- checks ArangoDB connectivity.

    Stream 7 PR 3 -- E.2: every failure here increments
    ``aoe_db_connection_errors_total{reason=...}``, which feeds the
    alert rule that pages on Arango unreachability. The ``reason``
    label is bucketed to keep cardinality low (``timeout`` / ``auth``
    / ``unknown``); we don't include the raw exception message
    because it carries unbounded variation.
    """
    try:
        db = get_db()
        db.version()
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        DB_CONNECTION_ERRORS.labels(reason=_classify_db_error(e)).inc()
        return {"status": "not_ready", "database": str(e)}


def _classify_db_error(exc: Exception) -> str:
    """Bucket a DB exception into a small set of metric labels.

    The full exception message is high-cardinality (varies by host,
    error code, retry count) and would blow up Prometheus storage.
    We map to three coarse buckets that cover the failure modes
    operators actually need to distinguish:

    * ``timeout``   -- network / Arango unresponsive
    * ``auth``      -- credentials / DB-not-found / permission denied
    * ``unknown``   -- anything else; falls through to the catch-all
                       so the metric still ticks even on novel errors

    Match strings are intentionally loose because python-arango
    surfaces errors as ``ServerConnectionError`` / ``HTTPError`` /
    ``ArangoServerError`` with descriptive ``str(exc)`` payloads
    that don't share a common attribute we can branch on.
    """
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text or "unreachable" in text:
        return "timeout"
    if "auth" in text or "unauthorized" in text or "permission" in text or "denied" in text:
        return "auth"
    return "unknown"
