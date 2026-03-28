# ADR 004: Authentication and Authorization Approach

**Status:** Accepted
**Date:** 2026-03-10
**Decision Makers:** AOE Core Team

---

## Context

AOE is a multi-tenant platform where organizations upload confidential documents and manage proprietary ontology extensions. The system needs:

- **Authentication** — verify user identity
- **Authorization** — enforce role-based access to features
- **Organization isolation** — ensure tenants only see their own data
- **MCP auth** — API key authentication for runtime MCP access by AI agents

### Requirements

| Requirement | Detail |
|-------------|--------|
| Multi-tenant isolation | All queries filtered by `org_id`; no cross-tenant data leakage |
| Role-based access | 4 roles with different capabilities |
| Stateless API auth | JWT tokens for REST API |
| MCP auth | API keys for runtime MCP (SSE transport) |
| External IdP support | Compatible with Auth0, Keycloak, or any OIDC provider |
| Audit trail | All mutations logged with authenticated user identity |

## Decision

We chose **JWT-based authentication with RBAC (Role-Based Access Control)** implemented as FastAPI middleware, with API key authentication for the MCP server's SSE transport.

## Rationale

### Authentication: JWT via OAuth 2.0 / OIDC

- **Stateless** — JWT tokens are self-contained; no server-side session store needed
- **Standard protocol** — compatible with Auth0, Keycloak, Okta, Azure AD, and any OIDC provider
- **FastAPI native** — `fastapi.security` provides OAuth2 bearer token handling out of the box
- **Claims-based** — user ID, org_id, and role are embedded in the token, avoiding a database lookup per request

### Authorization: RBAC with 4 Roles

| Role | Permissions |
|------|------------|
| `admin` | Full access — user management, org settings, all ontology operations |
| `ontology_engineer` | Import/export ontologies, configure extraction, manage domain library |
| `domain_expert` | Curation (approve/reject/edit/merge), view pipeline status, view ontology |
| `viewer` | Read-only access to ontologies and pipeline status |

Role enforcement is implemented as FastAPI dependencies injected at the route level:

```python
@router.post("/decide")
async def record_decision(
    body: CurationDecisionCreate,
    user: AuthUser = Depends(require_role("domain_expert")),
) -> dict:
    ...
```

### MCP Authentication: API Keys

For runtime MCP access (SSE transport), JWT is impractical because MCP clients are typically headless agents without browser-based OAuth flows. Instead:

- API keys are stored as SHA-256 hashes in the `api_keys` collection
- Each key is scoped to an `org_id` with specific permissions
- Keys can be revoked or expired without affecting other tenants
- In stdio mode (development), authentication is bypassed

### Organization Isolation

Every tenant-scoped query includes an `org_id` filter, enforced at the repository layer:

- All `ontology_classes`, `ontology_properties`, documents, and extraction runs carry an `org_id` field
- Repository functions accept `org_id` from the authenticated user context
- Domain ontologies (Tier 1) are shared across orgs but read-only for non-admins
- The MCP server filters tool results by the authenticated org

## Consequences

### Positive

- Stateless auth scales horizontally — no shared session store
- Standard OIDC compatibility — organizations can bring their own IdP
- Role-based guards are declarative and co-located with route definitions
- API keys provide simple auth for AI agents without OAuth complexity
- Audit trail captures `user_id` from JWT claims on every mutation

### Negative

- JWT token revocation is not instant — tokens remain valid until expiry (mitigated by short expiry + refresh tokens)
- API key management is a separate auth surface to maintain alongside JWT
- RBAC is coarse-grained — no per-ontology or per-document permissions (acceptable for v1.0)

### Trade-offs Considered

| Alternative | Why Not |
|-------------|---------|
| Session-based auth | Requires shared session store; complicates horizontal scaling |
| API keys for everything | No standard IdP integration; no SSO for human users |
| ABAC (Attribute-Based) | Over-engineered for 4 roles; RBAC is sufficient for v1.0 |
| Per-resource permissions | Significant complexity; can be added later as RBAC extension |
