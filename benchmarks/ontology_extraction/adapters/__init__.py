"""Extractor adapters — pluggable backends that map document text to classes + triples."""

from .base import ExtractionAdapter, ExtractionResult
from .mock import MockAdapter

__all__ = ["ExtractionAdapter", "ExtractionResult", "MockAdapter"]
