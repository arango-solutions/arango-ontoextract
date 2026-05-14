#!/usr/bin/env bash
# ============================================================================
# sync-requirements.sh
# ----------------------------------------------------------------------------
# Regenerate (or verify) `requirements.txt` from the canonical dependency
# list in `backend/pyproject.toml`.
#
# Why this exists:
#   - Production builds (Dockerfile, Container Manager packaging, CI) install
#     from `backend/pyproject.toml` + `backend/uv.lock`.
#   - The BYOC build hook `scripts/prepareproject.sh` runs `pip install -r
#     requirements.txt`. Until BYOC can read pyproject.toml directly, we keep
#     `requirements.txt` as a derived artefact.
#
# Usage:
#   bash scripts/sync-requirements.sh           # rewrite requirements.txt
#   bash scripts/sync-requirements.sh --check   # exit 1 if out of sync (CI)
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYPROJECT="${REPO_ROOT}/backend/pyproject.toml"
TARGET="${REPO_ROOT}/requirements.txt"

if [[ ! -f "${PYPROJECT}" ]]; then
    echo "ERROR: ${PYPROJECT} not found" >&2
    exit 2
fi

# Extract the [project].dependencies array. We deliberately use Python (already
# a build-time dependency for any consumer of this repo) instead of `tomlq` /
# `yq` so this script has no extra prereqs.
GENERATED="$(python3 - <<PY
import sys
import tomllib
from pathlib import Path

with Path("${PYPROJECT}").open("rb") as fh:
    data = tomllib.load(fh)

deps = data.get("project", {}).get("dependencies", [])
if not deps:
    print("ERROR: no [project].dependencies in ${PYPROJECT}", file=sys.stderr)
    sys.exit(2)

header = (
    "# AUTO-GENERATED — do not edit by hand.\n"
    "# Regenerate with: make sync-requirements\n"
    "# Source of truth: backend/pyproject.toml ([project].dependencies)\n"
    "#\n"
    "# Consumed by scripts/prepareproject.sh (BYOC build hook). Production\n"
    "# builds (Dockerfile, Container Manager) install from backend/pyproject.toml\n"
    "# directly; this file exists only to keep BYOC working until that flow can\n"
    "# read pyproject.toml.\n"
)
print(header + "\n".join(deps))
PY
)"

case "${1:-}" in
    --check)
        if ! diff -u "${TARGET}" <(printf '%s\n' "${GENERATED}") > /dev/null 2>&1; then
            echo "ERROR: ${TARGET} is out of sync with ${PYPROJECT}." >&2
            echo "Run: make sync-requirements" >&2
            exit 1
        fi
        echo "OK: requirements.txt is in sync with backend/pyproject.toml"
        ;;
    "")
        printf '%s\n' "${GENERATED}" > "${TARGET}"
        echo "Wrote ${TARGET}"
        ;;
    *)
        echo "Usage: $0 [--check]" >&2
        exit 2
        ;;
esac
