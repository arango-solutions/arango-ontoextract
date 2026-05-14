#!/usr/bin/env bash
# Run ESLint --fix on staged frontend files passed by the pre-commit framework.
#
# Pre-commit passes repo-relative paths (e.g. `frontend/src/foo.tsx`).
# ESLint resolves files relative to its cwd; we strip the `frontend/` prefix
# and run from `frontend/` so the project's flat config + rules apply.
set -euo pipefail

if [[ $# -eq 0 ]]; then
	exit 0
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}/frontend"

if [[ ! -d node_modules ]]; then
	echo "eslint-staged: frontend/node_modules missing; run 'cd frontend && npm ci'" >&2
	exit 1
fi

rel=()
for f in "$@"; do
	rel+=("${f#frontend/}")
done

npm exec --silent -- eslint --fix --max-warnings=0 "${rel[@]}"
