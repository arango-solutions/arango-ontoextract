"""Operational benchmarks (Stream 7 PR 4 -- E.5).

These benchmarks measure the system's *operational* characteristics:
API latency, materialization throughput, temporal-snapshot cost.
They complement ``benchmarks/ontology_extraction/`` which measures
*quality* (precision / recall against Re-DocRED, WebNLG).

All ops benchmarks are designed to run on a dev laptop without a
real ArangoDB -- expensive DB calls are mocked so the numbers
reflect the application code paths (serialization, routing,
business logic), not the underlying database. For real-DB
end-to-end benchmarks, see ``docs/benchmarks.md`` "How to Run"
section.
"""
