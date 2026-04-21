"""Make the repo root importable so ``benchmarks.ontology_extraction`` resolves.

The benchmark harness is intentionally outside ``backend/`` so it can run
against the AOE adapter (which imports the backend package) or against a mock
adapter without any backend dependencies. Pytest is invoked with
``rootdir=<repo root>`` in the make target; for ad-hoc ``pytest
benchmarks/...`` runs we prepend the repo root to ``sys.path`` here.
"""
from __future__ import annotations

import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
