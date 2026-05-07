"""Single source of truth for temporal sentinel constants.

Per ``backend/app/db/AGENTS.md``:

    All versioned collections use ``created`` / ``expired`` interval semantics
    with ``NEVER_EXPIRES = sys.maxsize``.

This module exists so the sentinel is declared exactly once and imported
everywhere else (services, API, MCP tools, migrations, tests). Importing it
rather than redeclaring it prevents accidental drift to ``9223372036854775807``,
``0``, or ``None`` — all of which have appeared in older code.

Usage:

    from app.db.temporal_constants import NEVER_EXPIRES
"""

from __future__ import annotations

import sys

#: Sentinel value used by ``expired`` to mean "currently active / never
#: expired". Chosen as ``sys.maxsize`` (platform-dependent maximum signed
#: integer) so range scans on ``[created, expired]`` MDI indexes need no
#: special-case handling. PRD §5.3.
NEVER_EXPIRES: int = sys.maxsize
