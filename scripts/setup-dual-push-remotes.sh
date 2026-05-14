#!/usr/bin/env bash
# setup-dual-push-remotes.sh — one-shot reconfiguration of git remotes for
# the "personal fork = active dev, org repo = release artifact" workflow.
#
# Reconfigures the local clone's remotes so that:
#   origin    -> personal fork           (default for `git push`)
#   upstream  -> org/release repo        (explicit pushes only)
#
# Detects and fixes the common dual-push misconfiguration where origin has
# multiple push URLs (one for fork, one for org). After this script runs,
# `git push` only ever hits the personal fork.
#
# Idempotent: rerun safely.
#
# Configuration (env vars; sane defaults for arango-ontoextract):
#   ORIGIN_URL       URL the personal fork (origin) should fetch+push to.
#                    Default: derived from current origin's fetch URL if
#                    it already points at a personal fork pattern; else
#                    error and ask user to set explicitly.
#   UPSTREAM_URL     URL the org/release remote should fetch+push to.
#                    Default: discovered by scanning existing remotes for
#                    one matching UPSTREAM_PROTECTED_URL_PATTERN; else
#                    error and ask user to set explicitly.
#   UPSTREAM_PROTECTED_URL_PATTERN
#                    Substring used both for discovery and as the value
#                    saved into the protect-upstream-push.sh hook config.
#                    Default: "arango-solutions/"
#   UPSTREAM_REMOTE_NAME
#                    What to name the protected remote.
#                    Default: "upstream" (GitHub fork-workflow convention)
#   DROP_REMOTES     Space-separated list of remote names to remove if
#                    present (cleanup of legacy remotes).
#                    Default: "" (don't remove anything)

set -euo pipefail

PATTERN="${UPSTREAM_PROTECTED_URL_PATTERN:-arango-solutions/}"
UPSTREAM_REMOTE_NAME="${UPSTREAM_REMOTE_NAME:-upstream}"

cyan() { printf '\033[36m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }

if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]]; then
	red "setup-dual-push-remotes: not inside a git work tree."
	exit 1
fi

cyan "==> Current remotes:"
git remote -v | sed 's/^/    /'
echo

# Discover URLs from existing config when not explicitly provided.
discovered_origin_fetch="$(git remote get-url origin 2>/dev/null || true)"
discovered_upstream=""
while IFS=$'\t' read -r name url_and_kind; do
	url="${url_and_kind% *}"
	kind="${url_and_kind##* }"
	[[ "${kind}" != "(fetch)" ]] && continue
	if grep -q -- "${PATTERN}" <<<"${url}"; then
		discovered_upstream="${url}"
	fi
done < <(git remote -v | awk '{print $1"\t"$2" "$3}')

ORIGIN_URL_FINAL="${ORIGIN_URL:-${discovered_origin_fetch}}"
UPSTREAM_URL_FINAL="${UPSTREAM_URL:-${discovered_upstream}}"

if [[ -z "${ORIGIN_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: cannot determine ORIGIN_URL."
	red "  Set it explicitly: ORIGIN_URL=https://github.com/<you>/<repo>.git $0"
	exit 1
fi

if [[ -z "${UPSTREAM_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: no remote URL matching '${PATTERN}' found."
	red "  Set it explicitly: UPSTREAM_URL=https://github.com/<org>/<repo>.git $0"
	red "  (or change UPSTREAM_PROTECTED_URL_PATTERN to match your org URL)"
	exit 1
fi

if [[ "${ORIGIN_URL_FINAL}" == "${UPSTREAM_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: ORIGIN_URL and UPSTREAM_URL must differ."
	red "  ORIGIN_URL=${ORIGIN_URL_FINAL}"
	red "  UPSTREAM_URL=${UPSTREAM_URL_FINAL}"
	exit 1
fi

cyan "==> Target layout:"
echo "    origin                            ${ORIGIN_URL_FINAL}"
echo "    ${UPSTREAM_REMOTE_NAME}$(printf '%*s' $((34 - ${#UPSTREAM_REMOTE_NAME})) '')${UPSTREAM_URL_FINAL}"
echo

# 1) Repoint origin (single fetch + single push URL = the personal fork).
if [[ "$(git remote get-url origin 2>/dev/null || true)" != "${ORIGIN_URL_FINAL}" ]]; then
	cyan "==> Updating origin fetch URL"
	git remote set-url origin "${ORIGIN_URL_FINAL}"
fi

# Strip any extra push URLs on origin (this is the dual-push misconfig).
# `git remote set-url --delete --push origin <url>` removes one URL at a
# time; loop until only the canonical one remains.
while true; do
	mapfile -t push_urls < <(git remote get-url --push --all origin 2>/dev/null || true)
	# If there's exactly one push URL and it equals ORIGIN_URL_FINAL, done.
	if [[ "${#push_urls[@]}" -le 1 ]] && [[ "${push_urls[0]:-${ORIGIN_URL_FINAL}}" == "${ORIGIN_URL_FINAL}" ]]; then
		break
	fi
	stripped=0
	for url in "${push_urls[@]}"; do
		if [[ "${url}" != "${ORIGIN_URL_FINAL}" ]]; then
			cyan "==> Removing extra push URL from origin: ${url}"
			git remote set-url --delete --push origin "${url}"
			stripped=1
			break
		fi
	done
	# Belt-and-suspenders: if every push URL matches but there are still
	# multiple entries (dupes), force-set to the canonical one.
	if [[ "${stripped}" -eq 0 ]]; then
		cyan "==> Collapsing duplicate origin push URLs to canonical"
		git remote set-url --push origin "${ORIGIN_URL_FINAL}"
		break
	fi
done

# 2) Ensure upstream exists with the right URL. If a remote with the
# UPSTREAM_REMOTE_NAME already exists pointing somewhere else, repoint it.
# If a different remote (e.g. literal "arango-solutions") already points at
# UPSTREAM_URL_FINAL, rename it to UPSTREAM_REMOTE_NAME.
if git remote get-url "${UPSTREAM_REMOTE_NAME}" >/dev/null 2>&1; then
	current="$(git remote get-url "${UPSTREAM_REMOTE_NAME}")"
	if [[ "${current}" != "${UPSTREAM_URL_FINAL}" ]]; then
		cyan "==> Repointing ${UPSTREAM_REMOTE_NAME} from ${current} to ${UPSTREAM_URL_FINAL}"
		git remote set-url "${UPSTREAM_REMOTE_NAME}" "${UPSTREAM_URL_FINAL}"
	fi
else
	# Find any remote (other than origin) whose URL matches.
	existing_name=""
	while IFS=$'\t' read -r name url_and_kind; do
		[[ "${name}" == "origin" ]] && continue
		url="${url_and_kind% *}"
		if [[ "${url}" == "${UPSTREAM_URL_FINAL}" ]]; then
			existing_name="${name}"
			break
		fi
	done < <(git remote -v | awk '{print $1"\t"$2" "$3}')

	if [[ -n "${existing_name}" ]]; then
		cyan "==> Renaming '${existing_name}' -> '${UPSTREAM_REMOTE_NAME}'"
		git remote rename "${existing_name}" "${UPSTREAM_REMOTE_NAME}"
	else
		cyan "==> Adding remote '${UPSTREAM_REMOTE_NAME}' -> ${UPSTREAM_URL_FINAL}"
		git remote add "${UPSTREAM_REMOTE_NAME}" "${UPSTREAM_URL_FINAL}"
	fi
fi

# Make sure upstream's push URL is the canonical one too (no dual-push
# weirdness left over from a previous configuration).
git remote set-url --push "${UPSTREAM_REMOTE_NAME}" "${UPSTREAM_URL_FINAL}"

# 3) Optional: drop legacy/extra remotes.
if [[ -n "${DROP_REMOTES:-}" ]]; then
	for r in ${DROP_REMOTES}; do
		if git remote get-url "${r}" >/dev/null 2>&1; then
			yellow "==> Removing remote '${r}'"
			git remote remove "${r}"
		fi
	done
fi

echo
cyan "==> Final remote layout:"
git remote -v | sed 's/^/    /'

cat <<EOF

==> Setup complete. Daily workflow:
    git push                          # → origin (your personal fork only)
    make release-to-org TAG=vX.Y.Z    # → ${UPSTREAM_REMOTE_NAME}/main + tag (release)
    make sync-from-org                # ← pull merged commits from ${UPSTREAM_REMOTE_NAME}/main

The protect-upstream-push pre-push hook will refuse direct pushes of
'main' to '${UPSTREAM_REMOTE_NAME}' unless HEAD is at an annotated release tag.
EOF
