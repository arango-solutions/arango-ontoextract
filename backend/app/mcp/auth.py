"""Organization-scoped authentication for the AOE MCP server.

Provides API key validation and org context for multi-tenant isolation.
In dev mode (stdio transport), auth is skipped and a default org is used.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.db.client import get_db
from app.db.utils import run_aql

log = logging.getLogger(__name__)

DEFAULT_ORG_ID = "default"
DEFAULT_PERMISSIONS = frozenset(
    {
        "ontology:read",
        "ontology:write",
        "extraction:trigger",
        "extraction:read",
        "er:read",
        "er:trigger",
        "export:read",
        "temporal:read",
        "system:health",
    }
)


@dataclass(frozen=True)
class OrgContext:
    """Organization context extracted from MCP request metadata."""

    org_id: str
    permissions: frozenset[str]
    api_key_id: str | None = None

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def can_read_ontology(self) -> bool:
        return self.has_permission("ontology:read")

    def can_write_ontology(self) -> bool:
        return self.has_permission("ontology:write")

    def can_trigger_extraction(self) -> bool:
        return self.has_permission("extraction:trigger")

    def can_trigger_er(self) -> bool:
        return self.has_permission("er:trigger")


_DEV_CONTEXT = OrgContext(
    org_id=DEFAULT_ORG_ID,
    permissions=DEFAULT_PERMISSIONS,
    api_key_id="dev",
)


def get_dev_context() -> OrgContext:
    """Return a default org context for development/stdio mode."""
    return _DEV_CONTEXT


def validate_api_key(api_key: str) -> dict[str, Any]:
    """Validate an API key and return org_id and permissions.

    Looks up the key in the ``api_keys`` collection. Returns an error dict
    if the key is invalid, expired, or revoked.
    """
    try:
        db = get_db()

        if not db.has_collection("api_keys"):
            return {
                "valid": False,
                "error": "API key authentication not configured (no api_keys collection)",
            }

        key_hash = _hash_api_key(api_key)

        results = list(
            run_aql(
                db,
                """\
FOR k IN api_keys
  FILTER k.key_hash == @hash
  FILTER k.status == "active"
  LIMIT 1
  RETURN k""",
                bind_vars={"hash": key_hash},
            )
        )

        if not results:
            log.warning("invalid API key attempted")
            return {"valid": False, "error": "Invalid or revoked API key"}

        key_doc = results[0]

        if key_doc.get("expires_at") and key_doc["expires_at"] < time.time():
            return {"valid": False, "error": "API key has expired"}

        permissions = frozenset(key_doc.get("permissions", list(DEFAULT_PERMISSIONS)))

        return {
            "valid": True,
            "org_id": key_doc.get("org_id", DEFAULT_ORG_ID),
            "api_key_id": key_doc.get("_key"),
            "permissions": list(permissions),
        }
    except Exception as exc:
        log.exception("API key validation failed")
        return {"valid": False, "error": f"Validation error: {exc}"}


def resolve_org_context(
    *,
    api_key: str | None = None,
    transport: str = "stdio",
) -> OrgContext:
    """Resolve the organization context for an MCP request.

    - stdio transport: returns dev context (no auth required)
    - SSE transport without API key: returns dev context with a warning
    - SSE transport with API key: validates and returns org-scoped context
    """
    if transport == "stdio":
        return get_dev_context()

    if not api_key:
        log.warning("SSE request without API key — using dev context")
        return get_dev_context()

    result = validate_api_key(api_key)
    if not result.get("valid"):
        log.warning(
            "API key validation failed",
            extra={"error": result.get("error")},
        )
        return get_dev_context()

    return OrgContext(
        org_id=result["org_id"],
        permissions=frozenset(result.get("permissions", list(DEFAULT_PERMISSIONS))),
        api_key_id=result.get("api_key_id"),
    )


def filter_by_org(
    data: list[dict[str, Any]],
    org_context: OrgContext,
    org_field: str = "org_id",
) -> list[dict[str, Any]]:
    """Filter a list of dicts to only include items belonging to the org.

    Items without an org_id field are included (shared/global data).
    The default org sees everything.
    """
    if org_context.org_id == DEFAULT_ORG_ID:
        return data

    return [
        item
        for item in data
        if item.get(org_field) is None or item.get(org_field) == org_context.org_id
    ]


def _hash_api_key(api_key: str) -> str:
    """Create a SHA-256 hash of the API key for storage comparison."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
