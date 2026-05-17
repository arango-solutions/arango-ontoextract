"""Bundled, read-only data files used at runtime.

Currently:

* ``standard_ontology_catalog.json`` -- the H.5 standard-ontology
  catalog metadata.
* ``ontologies/`` -- bundled OWL/TTL files for ontologies the catalog
  marks as ``source.kind == "bundled"``. Optional optimization: any
  catalog entry can ship with a bundled file so it imports offline; the
  catalog importer falls back to URL fetch when no bundle is present.

This is a Python package only so that ``importlib.resources`` can find
the files in installed wheels.
"""
