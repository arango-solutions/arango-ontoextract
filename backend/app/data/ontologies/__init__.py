"""Bundled standard ontology files (Stream 1 H.5).

Files here are optional optimizations -- the catalog importer reads
them when ``catalog_entry.source.kind == "bundled"`` and ``path`` is
populated. Missing files cause a clear error rather than a silent
fallback so deployment surprises stay loud.

To extend: drop a new ``foo.ttl`` here, add a catalog entry with
``source: {kind: "bundled", path: "foo.ttl"}``, and ship.
"""
