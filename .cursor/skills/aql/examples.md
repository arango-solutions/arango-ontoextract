## MCP-first "explore then query" recipes

These are practical sequences an agent can follow when working via the Arango MCP server.

### 1) Explore what's available (DB -> collections -> graphs)

- List databases
- Pick the target database (`multi-tenant-blueprint`)
- List collections
- List graphs (`network_assets_smartgraph`, `taxonomy_satellite_graph`)

### 2) Always fetch manuals before drafting AQL

Before writing/executing AQL, fetch:
- `aql_ref`
- `optimization`

### 3) Start small: validate shape before scaling

Use `LIMIT 5` or `LIMIT 10`, confirm result shape, then scale.

---

## Working queries from this project

These are the saved queries installed in the ArangoDB UI. Each is a tested, working example. Default bind var `tenantId` uses `"1b45406a99d9"` (the first tenant in the demo data).

---

### 4) Tenant Overview

Summary of all tenants with device, software, and location counts.

```aql
FOR d IN Device
  COLLECT tenant = d.tenantId
  LET devices = LENGTH(FOR x IN Device FILTER x.tenantId == tenant RETURN 1)
  LET software = LENGTH(FOR x IN Software FILTER x.tenantId == tenant RETURN 1)
  LET locations = LENGTH(FOR x IN Location FILTER x.tenantId == tenant RETURN 1)
  SORT devices DESC
  RETURN {
    tenantId: tenant,
    devices: devices,
    software: software,
    locations: locations,
    total: devices + software + locations
  }
```

Bind vars: none

---

### 5) Devices for Tenant

List all devices for a specific tenant with their details.

```aql
FOR d IN Device
  FILTER d.tenantId == @tenantId
  SORT d.type, d.name
  RETURN {
    key: d._key,
    name: d.name,
    type: d.type,
    model: d.model,
    ipAddress: d.ipAddress,
    os: d.operatingSystem,
    created: d.created
  }
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9" }
```

---

### 6) Device Version History (Time Travel)

Show all versions of a device through its ProxyIn -> hasVersion -> Device chain.

```aql
FOR proxy IN DeviceProxyIn
  FILTER proxy.tenantId == @tenantId
  FILTER proxy._key == @deviceProxy
  FOR v, e IN 1..1 OUTBOUND proxy hasVersion
    SORT e.created DESC
    RETURN {
      proxyName: proxy.name,
      version: v.name,
      model: v.model,
      ipAddress: v.ipAddress,
      os: v.operatingSystem,
      osVersion: v.osVersion,
      created: e.created,
      expired: e.expired,
      isCurrent: e.expired == 9223372036854775807
    }
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9", "deviceProxy": "1b45406a99d9:device1" }
```

Notes:
- Traverses from the stable proxy to all version snapshots
- `isCurrent` uses the `NEVER_EXPIRES` sentinel (`9223372036854775807`)
- Results sorted newest-first by `e.created`

---

### 7) Software Version History (Time Travel)

Show all versions of a software instance through its ProxyIn -> hasVersion -> Software chain.

```aql
FOR proxy IN SoftwareProxyIn
  FILTER proxy.tenantId == @tenantId
  FILTER proxy._key == @softwareProxy
  FOR v, e IN 1..1 OUTBOUND proxy hasVersion
    SORT e.created DESC
    RETURN {
      proxyName: proxy.name,
      version: v.name,
      softwareVersion: v.version,
      port: v.portNumber,
      enabled: v.isEnabled,
      created: e.created,
      expired: e.expired,
      isCurrent: e.expired == 9223372036854775807
    }
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9", "softwareProxy": "1b45406a99d9:software1" }
```

---

### 8) Point-in-Time Snapshot (Time Travel)

Show all devices and software that were active at a specific point in time.

```aql
LET ts = @timestamp
LET devices = (
  FOR d IN Device
    FILTER d.tenantId == @tenantId
    FILTER d.created <= ts AND d.expired > ts
    RETURN { collection: "Device", name: d.name, type: d.type, ip: d.ipAddress }
)
LET software = (
  FOR s IN Software
    FILTER s.tenantId == @tenantId
    FILTER s.created <= ts AND s.expired > ts
    RETURN { collection: "Software", name: s.name, type: s.type, version: s.version }
)
RETURN {
  queryTime: ts,
  activeDevices: LENGTH(devices),
  activeSoftware: LENGTH(software),
  devices: devices,
  software: software
}
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9", "timestamp": 1762881314 }
```

Notes:
- Uses the MDI-prefixed index on `[created, expired]`
- Both `Device` and `Software` are queried with interval semantics
- `timestamp` should be a unix timestamp (float)

---

### 9) Tenant Isolation Proof

Verify SmartGraph tenant isolation -- traverse from one tenant and confirm no cross-tenant leakage.

```aql
LET startTenant = @tenantId
LET traversed = (
  FOR d IN Device
    FILTER d.tenantId == startTenant
    LIMIT 5
    FOR v, e, p IN 1..3 ANY d
      hasConnection, hasLocation, hasDeviceSoftware, hasVersion
      RETURN DISTINCT v.tenantId
)
LET uniqueTenants = UNIQUE(traversed)
RETURN {
  startTenant: startTenant,
  tenantsReached: uniqueTenants,
  isolationVerified: LENGTH(uniqueTenants) <= 1 OR (LENGTH(uniqueTenants) == 1 AND uniqueTenants[0] == startTenant),
  traversalCount: LENGTH(traversed)
}
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9" }
```

Notes:
- Traverses up to 3 hops across multiple edge collections
- `isolationVerified` should always be `true` if SmartGraph sharding is working correctly
- Uses edge collection list (not `GRAPH`) for explicit control

---

### 10) Network Topology (Device Connections)

Show the network topology for a tenant -- devices and their connections.

```aql
FOR c IN hasConnection
  FILTER c.tenantId == @tenantId
  LET fromProxy = DOCUMENT(c._from)
  LET toProxy = DOCUMENT(c._to)
  RETURN {
    from: fromProxy.name,
    to: toProxy.name,
    connectionType: c.connectionType,
    bandwidth: c.bandwidthCapacity,
    latency: c.networkLatency
  }
```

Bind vars:
```json
{ "tenantId": "1b45406a99d9" }
```

Notes:
- `hasConnection` edges connect `DeviceProxyOut` -> `DeviceProxyIn` (proxy-to-proxy)
- `DOCUMENT()` resolves the proxy vertex from the edge `_from`/`_to` references

---

### 11) Device Full Context (Software + Location + Taxonomy)

For a given device version, show its installed software, location, and taxonomy classification.

```aql
FOR d IN Device
  FILTER d._key == @deviceKey
  LET proxyOut = FIRST(
    FOR po IN DeviceProxyOut
      FILTER po._key == SPLIT(d._key, '-')[0]
      RETURN po
  )
  LET software = (
    FOR sw, e IN 2..2 OUTBOUND proxyOut hasDeviceSoftware, hasVersion
      FILTER IS_SAME_COLLECTION('Software', sw)
      RETURN { name: sw.name, version: sw.version, port: sw.portNumber, enabled: sw.isEnabled }
  )
  LET location = FIRST(
    FOR loc, e IN 1..1 OUTBOUND proxyOut hasLocation
      RETURN { name: loc.name, address: loc.streetAddress }
  )
  LET classes = (
    FOR cls, e IN 1..1 OUTBOUND d type
      RETURN { className: cls.name, category: cls.category, confidence: e.confidence }
  )
  RETURN {
    device: d.name,
    type: d.type,
    ip: d.ipAddress,
    os: CONCAT(d.operatingSystem, ' ', d.osVersion),
    location: location,
    software: software,
    classification: classes
  }
```

Bind vars:
```json
{ "deviceKey": "1b45406a99d9:device1-0" }
```

Notes:
- `SPLIT(d._key, '-')[0]` strips the version suffix to find the proxy
- Software traversal goes 2 hops: `DeviceProxyOut -> hasDeviceSoftware -> SoftwareProxyIn`, then `SoftwareProxyIn -> hasVersion -> Software`
- `IS_SAME_COLLECTION('Software', sw)` filters to only Software vertices (skipping proxies)
- Classification (`type` edges) goes directly from the versioned `Device` to `Class` (satellite)

---

### 12) Taxonomy Class Hierarchy

Show the taxonomy class hierarchy from the satellite Class collection.

```aql
FOR c IN Class
  COLLECT category = c.category INTO classes
  SORT category
  RETURN {
    category: category,
    classCount: LENGTH(classes),
    classes: (
      FOR cls IN classes
        SORT cls.c.name
        RETURN { name: cls.c.name, description: cls.c.description }
    )
  }
```

Bind vars: none

Notes:
- `Class` is a satellite collection (replicated to all DB servers)
- No `tenantId` filter needed -- taxonomy is shared across all tenants

---

### 13) Collection Statistics

Document counts for all graph collections, broken down by tenant.

```aql
LET devicesByTenant = (
  FOR d IN Device COLLECT t = d.tenantId WITH COUNT INTO c RETURN {tenant: t, count: c}
)
LET softwareByTenant = (
  FOR s IN Software COLLECT t = s.tenantId WITH COUNT INTO c RETURN {tenant: t, count: c}
)
LET locationsByTenant = (
  FOR l IN Location COLLECT t = l.tenantId WITH COUNT INTO c RETURN {tenant: t, count: c}
)
RETURN {
  totalDevices: SUM(devicesByTenant[*].count),
  totalSoftware: SUM(softwareByTenant[*].count),
  totalLocations: SUM(locationsByTenant[*].count),
  devicesByTenant: devicesByTenant,
  softwareByTenant: softwareByTenant,
  locationsByTenant: locationsByTenant
}
```

Bind vars: none

Notes:
- Uses `COLLECT ... WITH COUNT INTO` for efficient aggregation
- `[*].count` is the AQL expansion operator for extracting a field from an array of objects

---

## Generic skeletons (for quick reference)

### Filtered query with bind vars

```aql
FOR d IN @@col
  FILTER d.@field == @value
  LIMIT @limit
  RETURN d
```

Bind vars:
```json
{ "@col": "Device", "field": "status", "value": "active", "limit": 10 }
```

### Quick sample from a collection

```aql
FOR d IN @@col
  LIMIT @limit
  RETURN d
```

### Named graph traversal (paths)

```aql
FOR v, e, p IN 1..@depth OUTBOUND @start GRAPH @graphName
  LIMIT @limit
  RETURN {
    vertices: p.vertices[*]._id,
    edges: p.edges[*]._id
  }
```

### Checklist when a query is slow

- Add/strengthen FILTERs (more selective).
- Return fewer fields (projection).
- Add LIMIT while iterating.
- Check for existing indexes; if none, propose an index (only if user wants).
- Re-read optimization manual and refine to a recommended pattern.
- For temporal queries, ensure both `created` and `expired` are in FILTER to use MDI-prefixed index.
