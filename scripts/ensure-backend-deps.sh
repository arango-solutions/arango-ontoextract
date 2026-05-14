#!/usr/bin/env bash
# Idempotent backend venv + dev-deps bootstrap.
#
# Why a script (not Makefile recipes): the venv may be uv-managed (no pip)
# OR stdlib-venv-managed (has pip). Both paths must work, and Make's tab
# rules make multi-line conditionals fragile. This is the one place we
# centralise that logic — entrypoint, Makefile, and pre-commit installs all
# call through here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/backend"

if [[ ! -x .venv/bin/python ]]; then
	echo "==> Creating backend/.venv (uv if available, else stdlib venv)..."
	if command -v uv >/dev/null 2>&1; then
		uv venv .venv
	else
		python3 -m venv .venv
	fi
fi

PY=".venv/bin/python"

if command -v uv >/dev/null 2>&1; then
	echo "==> uv pip install -e \".[dev]\" (--python ${PY})"
	uv pip install -e ".[dev]" --python "${PY}"
elif "${PY}" -m pip --version >/dev/null 2>&1; then
	echo "==> python -m pip install -e \".[dev]\""
	"${PY}" -m pip install -e ".[dev]"
else
	echo "==> bootstrapping pip via ensurepip..."
	"${PY}" -m ensurepip --upgrade --default-pip
	"${PY}" -m pip install -e ".[dev]"
fi
