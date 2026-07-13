#!/usr/bin/env bash
# ============================================================================
# check-version-parity.sh
# ----------------------------------------------------------------------------
# Verify the frontend package version matches the backend single source of
# truth. The backend `__version__` in `backend/app/__init__.py` is canonical
# (see the module docstring there); `frontend/package.json` "version" must
# track it and is bumped in the same release commit.
#
# Why this exists:
#   The frontend version silently drifted — it was left at 1.0.0 through the
#   v1.1.0 release while the backend advanced — because nothing tied the two
#   together. This guard fails the commit whenever only one side is bumped.
#
# It is CHECK-ONLY (no auto-fix): the fix is a one-line human edit to
# package.json, and rewriting JSON from a hook risks clobbering formatting.
#
# Usage:
#   bash scripts/check-version-parity.sh    # exit 1 on mismatch
#
# Wired as a Tier-A pre-commit hook (fires when either version file is staged)
# and therefore also runs under `make pre-commit-run-all`, which gates
# `make release-to-org`.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INIT="${REPO_ROOT}/backend/app/__init__.py"
PKG="${REPO_ROOT}/frontend/package.json"

for f in "${INIT}" "${PKG}"; do
    if [[ ! -f "${f}" ]]; then
        echo "version-parity: ERROR: ${f} not found" >&2
        exit 2
    fi
done

# Backend: the line is `__version__ = "X.Y.Z"`. sed pulls the quoted value.
backend_ver="$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "${INIT}" | head -n1)"

# Frontend: parse package.json with the stdlib so we never rely on key order.
frontend_ver="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' "${PKG}")"

if [[ -z "${backend_ver}" ]]; then
    echo "version-parity: ERROR: could not read __version__ from ${INIT}" >&2
    exit 2
fi
if [[ -z "${frontend_ver}" ]]; then
    echo "version-parity: ERROR: could not read \"version\" from ${PKG}" >&2
    exit 2
fi

if [[ "${backend_ver}" != "${frontend_ver}" ]]; then
    cat >&2 <<EOF
version-parity: FRONTEND/BACKEND VERSION MISMATCH
  backend/app/__init__.py  __version__ = ${backend_ver}   (single source of truth)
  frontend/package.json    "version"   = ${frontend_ver}
Fix: set frontend/package.json "version" to ${backend_ver} — the two must match
at every release. (Then re-stage and re-commit.)
EOF
    exit 1
fi

echo "version-parity: OK (${backend_ver})"
