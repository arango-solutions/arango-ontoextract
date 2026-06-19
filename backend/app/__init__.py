"""Arango-OntoExtract backend package.

``__version__`` is the single source of truth for the backend version. It is
read both at build time (``pyproject.toml`` → ``[tool.hatch.version] path``)
and at runtime (FastAPI/OpenAPI ``version`` in ``app.main`` and the OpenTelemetry
``service.version`` in ``app.observability.tracing``), so bumping the release
line is a one-line change here. Use a PEP 440 dev suffix (``X.Y.Z.devN``)
between tagged releases; drop it when cutting ``vX.Y.Z`` via ``make
release-to-org``.
"""

from __future__ import annotations

__version__ = "1.0.0"
