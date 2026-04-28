#!/usr/bin/env bash
# Build a tarball for Arango Container Manager manual packaging.
#
# Layout: FLAT archive — entrypoint and pyproject.toml at the ROOT of the tar.
# entrypoint must be Python. Line 1 first token must be `entrypoint` (some hosts run python /project/$(awk '{print $1}' entrypoint)).
# Arango extracts the tarball into the service workdir and looks for ./entrypoint
# there; a nested layout (myservice/entrypoint only) fails with "No entrypoint found".
#
# Optional: PACKAGE_USE_TOPDIR=1 reproduces `tar -czf x.tar.gz myservice/` (nested).
#
# Optional: PACKAGE_INCLUDE_FRONTEND=1 bundles the Next.js static export (frontend/out)
# next to app/. Requires SERVICE_URL_PATH_PREFIX (same as backend) and Node/npm on PATH.
# Static export disables Next.js middleware at runtime (API auth still applies).
#
# macOS creates tar entries with Apple-specific PAX headers (e.g.
# LIBARCHIVE.xattr.com.apple.provenance). Linux extractors may warn or fail
# with "stream closed: EOF". We strip xattrs and disable copyfile metadata.
set -euo pipefail

# Prevent Finder/APFS extended attributes and AppleDouble files from entering the archive.
export COPYFILE_DISABLE=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${REPO_ROOT}/aoe-myservice.tar.gz}"
STAGE="$(mktemp -d)"
cleanup() { rm -rf "${STAGE}"; }
trap cleanup EXIT

NAME="${PACKAGE_DIR_NAME:-myservice}"
mkdir -p "${STAGE}/${NAME}"

cp -R "${REPO_ROOT}/backend/app" "${STAGE}/${NAME}/"
cp -R "${REPO_ROOT}/backend/migrations" "${STAGE}/${NAME}/"
cp "${REPO_ROOT}/backend/pyproject.toml" "${STAGE}/${NAME}/"
if [[ -f "${REPO_ROOT}/backend/uv.lock" ]]; then
	cp "${REPO_ROOT}/backend/uv.lock" "${STAGE}/${NAME}/"
fi
cp "${REPO_ROOT}/backend/entrypoint" "${STAGE}/${NAME}/entrypoint"
chmod +x "${STAGE}/${NAME}/entrypoint"
# Optional: ship repo-root .env so Container Manager picks up ARANGO_* without duplicating env in UI.
# Do not commit secrets; use UI env vars for production when preferred.
if [[ -f "${REPO_ROOT}/.env" ]]; then
	cp "${REPO_ROOT}/.env" "${STAGE}/${NAME}/.env"
fi

if [[ "${PACKAGE_INCLUDE_FRONTEND:-0}" == "1" ]]; then
	PREFIX="${SERVICE_URL_PATH_PREFIX:-}"
	PREFIX="${PREFIX%/}"
	if [[ -z "${PREFIX}" ]]; then
		echo "error: PACKAGE_INCLUDE_FRONTEND=1 requires SERVICE_URL_PATH_PREFIX (no trailing slash)" >&2
		exit 1
	fi
	if ! command -v npm >/dev/null 2>&1; then
		echo "error: PACKAGE_INCLUDE_FRONTEND=1 requires npm on PATH" >&2
		exit 1
	fi
	echo "==> Building static frontend (NEXT_PUBLIC_BASE_PATH=${PREFIX})..."
	(
		cd "${REPO_ROOT}/frontend"
		if [[ -f package-lock.json ]]; then
			npm ci
		else
			npm install
		fi
		rm -rf out .next
		AOE_STATIC_EXPORT=1 \
			NEXT_PUBLIC_BASE_PATH="${PREFIX}" \
			npm run build
	)
	mkdir -p "${STAGE}/${NAME}/frontend"
	cp -R "${REPO_ROOT}/frontend/out" "${STAGE}/${NAME}/frontend/out"
	echo "==> Included frontend/out in bundle"
fi

# Strip remaining extended attributes on macOS (avoids provenance/quarantine xattrs in PAX headers).
if [[ "$(uname -s)" == "Darwin" ]] && command -v xattr >/dev/null 2>&1; then
	xattr -cr "${STAGE}/${NAME}" 2>/dev/null || true
fi

# POSIX-friendly archive; GNU tar on Linux (cluster) extracts cleanly.
if [[ "${PACKAGE_USE_TOPDIR:-0}" == "1" ]]; then
	tar -czf "${OUT}" -C "${STAGE}" "${NAME}"
	echo "Wrote ${OUT} (nested: ${NAME}/…)"
else
	tar -czf "${OUT}" -C "${STAGE}/${NAME}" .
	echo "Wrote ${OUT} (flat: entrypoint + pyproject.toml at archive root)"
fi
