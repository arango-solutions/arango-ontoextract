#!/usr/bin/env bash
# setup-dual-push-remotes.sh — one-shot reconfiguration of git remotes for
# the "org repo = primary, personal fork = mirror" workflow.
#
# Reconfigures the local clone's remotes so that:
#   origin  -> FETCHES from the org repo, and PUSHES to BOTH the org repo
#              and the personal fork (two push URLs)
#   fork    -> personal fork only (explicit fetches / pushes)
#
# Net effect: `git pull` and `git status` read from the org repo, and a
# single `git push` lands on both repos.
#
# History (2026-09-08): this script previously enforced the opposite layout
# — origin = personal fork, upstream = org repo, and it actively STRIPPED
# extra push URLs so `git push` only ever hit the fork. The org repo was
# then reached only through `make release-to-org TAG=vX.Y.Z`, gated by
# scripts/githooks/protect-upstream-push.sh. That gate is now unwired (see
# .pre-commit-config.yaml) because the org repo is the primary.
#
# Idempotent: rerun safely.
#
# Configuration (env vars; sane defaults for arango-ontoextract):
#   ORG_URL          URL of the primary/org repo. Default: discovered by
#                    scanning existing remotes for ORG_URL_PATTERN.
#                    (UPSTREAM_URL is accepted as a legacy alias.)
#   FORK_URL         URL of the personal fork. Default: discovered as the
#                    first non-org remote URL.
#                    (ORIGIN_URL is accepted as a legacy alias.)
#   ORG_URL_PATTERN  Substring identifying the org repo among the remotes.
#                    Default: "arango-solutions/"
#                    (UPSTREAM_PROTECTED_URL_PATTERN is a legacy alias.)
#   ORG_REMOTE_NAME  What to name the primary remote.  Default: "origin"
#   FORK_REMOTE_NAME What to name the fork remote.     Default: "fork"
#   TRACK_BRANCH     Branch to repoint at the org remote. Default: "main"
#                    Set to "" to skip retargeting entirely.
#   DROP_REMOTES     Space-separated remote names to remove if present.
#                    Default: "" (don't remove anything)

set -euo pipefail

PATTERN="${ORG_URL_PATTERN:-${UPSTREAM_PROTECTED_URL_PATTERN:-arango-solutions/}}"
ORG_REMOTE_NAME="${ORG_REMOTE_NAME:-origin}"
FORK_REMOTE_NAME="${FORK_REMOTE_NAME:-fork}"
TRACK_BRANCH="${TRACK_BRANCH-main}"

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

# --- Discover the two URLs from whatever layout we're starting in --------
# Note: no `mapfile` / associative arrays anywhere in this script. macOS
# ships bash 3.2 and the end-to-end test in
# tests/unit/test_setup_dual_push_remotes.py runs it under /bin/bash, so a
# bash-4-only construct fails CI on macOS runners.
url_of() { git remote get-url "$1" 2>/dev/null || true; }
matches_org() { grep -q -- "${PATTERN}" <<<"$1"; }

# The org repo: prefer a remote already carrying the target name, then the
# names used by the previous layout, then any remote whose URL matches.
discovered_org=""
for cand in "${ORG_REMOTE_NAME}" upstream arango-solutions; do
	u="$(url_of "${cand}")"
	if [[ -n "${u}" ]] && matches_org "${u}"; then
		discovered_org="${u}"
		break
	fi
done
if [[ -z "${discovered_org}" ]]; then
	while IFS=$'\t' read -r name url_and_kind; do
		url="${url_and_kind% *}"
		kind="${url_and_kind##* }"
		[[ "${kind}" != "(fetch)" ]] && continue
		if matches_org "${url}"; then
			discovered_org="${url}"
			break
		fi
	done < <(git remote -v | awk '{print $1"\t"$2" "$3}')
fi

# The fork: whichever of `fork` / `origin` does NOT match the org pattern.
# Deliberately NOT "the first other remote" — that happily adopts an
# unrelated remote as the mirror, which is a genuinely bad outcome (you
# start force-feeding your commits to somebody else's repo). If neither
# candidate fits we bail and ask for FORK_URL explicitly.
discovered_fork=""
for cand in "${FORK_REMOTE_NAME}" "${ORG_REMOTE_NAME}"; do
	u="$(url_of "${cand}")"
	if [[ -n "${u}" ]] && ! matches_org "${u}"; then
		discovered_fork="${u}"
		break
	fi
done

ORG_URL_FINAL="${ORG_URL:-${UPSTREAM_URL:-${discovered_org}}}"
FORK_URL_FINAL="${FORK_URL:-${ORIGIN_URL:-${discovered_fork}}}"

if [[ -z "${ORG_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: no remote URL matching '${PATTERN}' found."
	red "  Set it explicitly: ORG_URL=https://github.com/<org>/<repo>.git $0"
	red "  (or change ORG_URL_PATTERN to match your org URL)"
	exit 1
fi

if [[ -z "${FORK_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: cannot determine FORK_URL."
	red "  Neither '${FORK_REMOTE_NAME}' nor '${ORG_REMOTE_NAME}' points at a non-org repo,"
	red "  and guessing from the other remotes risks mirroring to the wrong place."
	red "  Set it explicitly: FORK_URL=https://github.com/<you>/<repo>.git $0"
	exit 1
fi

if [[ "${ORG_URL_FINAL}" == "${FORK_URL_FINAL}" ]]; then
	red "setup-dual-push-remotes: ORG_URL and FORK_URL must differ."
	red "  ORG_URL=${ORG_URL_FINAL}"
	red "  FORK_URL=${FORK_URL_FINAL}"
	exit 1
fi

cyan "==> Target layout:"
echo "    ${ORG_REMOTE_NAME} (fetch)   ${ORG_URL_FINAL}"
echo "    ${ORG_REMOTE_NAME} (push)    ${ORG_URL_FINAL}"
echo "    ${ORG_REMOTE_NAME} (push)    ${FORK_URL_FINAL}"
echo "    ${FORK_REMOTE_NAME}          ${FORK_URL_FINAL}"
echo

# --- 1) Claim the name ORG_REMOTE_NAME for the org repo ------------------
# Whatever currently holds that name may be the fork (the old layout), in
# which case it has to move out of the way first.
if git remote get-url "${ORG_REMOTE_NAME}" >/dev/null 2>&1; then
	current="$(git remote get-url "${ORG_REMOTE_NAME}")"
	if [[ "${current}" != "${ORG_URL_FINAL}" ]]; then
		if [[ "${current}" == "${FORK_URL_FINAL}" ]] &&
			! git remote get-url "${FORK_REMOTE_NAME}" >/dev/null 2>&1; then
			cyan "==> '${ORG_REMOTE_NAME}' currently points at the fork; renaming to '${FORK_REMOTE_NAME}'"
			git remote rename "${ORG_REMOTE_NAME}" "${FORK_REMOTE_NAME}"
		else
			cyan "==> Repointing ${ORG_REMOTE_NAME} fetch URL to the org repo"
			git remote set-url "${ORG_REMOTE_NAME}" "${ORG_URL_FINAL}"
		fi
	fi
fi

if ! git remote get-url "${ORG_REMOTE_NAME}" >/dev/null 2>&1; then
	# Adopt an existing remote that already points at the org repo
	# (e.g. "upstream" from the old layout, or a literal "arango-solutions").
	existing_name=""
	while IFS=$'\t' read -r name url_and_kind; do
		url="${url_and_kind% *}"
		if [[ "${url}" == "${ORG_URL_FINAL}" ]]; then
			existing_name="${name}"
			break
		fi
	done < <(git remote -v | awk '{print $1"\t"$2" "$3}')

	if [[ -n "${existing_name}" ]]; then
		cyan "==> Renaming '${existing_name}' -> '${ORG_REMOTE_NAME}'"
		git remote rename "${existing_name}" "${ORG_REMOTE_NAME}"
	else
		cyan "==> Adding remote '${ORG_REMOTE_NAME}' -> ${ORG_URL_FINAL}"
		git remote add "${ORG_REMOTE_NAME}" "${ORG_URL_FINAL}"
	fi
fi

git remote set-url "${ORG_REMOTE_NAME}" "${ORG_URL_FINAL}"

# --- 2) Give ORG_REMOTE_NAME exactly two push URLs: org, then fork -------
# `git remote set-url --push <remote> <url>` does NOT replace a multi-value
# list — with more than one pushurl already configured it aborts with
#   warning: remote.<name>.pushurl has multiple values
#   fatal: could not set 'remote.<name>.pushurl'
# so clear the list at the config level first, then append both. Doing it
# unconditionally keeps this idempotent no matter what we started from.
cyan "==> Setting ${ORG_REMOTE_NAME} to dual-push (org + fork)"
git config --unset-all "remote.${ORG_REMOTE_NAME}.pushurl" 2>/dev/null || true
git remote set-url --add --push "${ORG_REMOTE_NAME}" "${ORG_URL_FINAL}"
git remote set-url --add --push "${ORG_REMOTE_NAME}" "${FORK_URL_FINAL}"

# --- 3) Ensure the fork remote exists and is single-homed ----------------
if git remote get-url "${FORK_REMOTE_NAME}" >/dev/null 2>&1; then
	if [[ "$(git remote get-url "${FORK_REMOTE_NAME}")" != "${FORK_URL_FINAL}" ]]; then
		cyan "==> Repointing ${FORK_REMOTE_NAME} to ${FORK_URL_FINAL}"
		git remote set-url "${FORK_REMOTE_NAME}" "${FORK_URL_FINAL}"
	fi
else
	existing_name=""
	while IFS=$'\t' read -r name url_and_kind; do
		[[ "${name}" == "${ORG_REMOTE_NAME}" ]] && continue
		url="${url_and_kind% *}"
		if [[ "${url}" == "${FORK_URL_FINAL}" ]]; then
			existing_name="${name}"
			break
		fi
	done < <(git remote -v | awk '{print $1"\t"$2" "$3}')

	if [[ -n "${existing_name}" ]]; then
		cyan "==> Renaming '${existing_name}' -> '${FORK_REMOTE_NAME}'"
		git remote rename "${existing_name}" "${FORK_REMOTE_NAME}"
	else
		cyan "==> Adding remote '${FORK_REMOTE_NAME}' -> ${FORK_URL_FINAL}"
		git remote add "${FORK_REMOTE_NAME}" "${FORK_URL_FINAL}"
	fi
fi
# Same multi-value caveat as above: a `fork` renamed out of the old
# dual-pushing `origin` inherits BOTH push URLs, so clear before setting.
git config --unset-all "remote.${FORK_REMOTE_NAME}.pushurl" 2>/dev/null || true
git remote set-url --add --push "${FORK_REMOTE_NAME}" "${FORK_URL_FINAL}"

# --- 4) Point the working branch at the org remote -----------------------
if [[ -n "${TRACK_BRANCH}" ]] && git rev-parse --verify "${TRACK_BRANCH}" >/dev/null 2>&1; then
	if git ls-remote --exit-code --heads "${ORG_REMOTE_NAME}" "${TRACK_BRANCH}" >/dev/null 2>&1; then
		cyan "==> Pointing '${TRACK_BRANCH}' at ${ORG_REMOTE_NAME}/${TRACK_BRANCH}"
		git fetch --quiet "${ORG_REMOTE_NAME}" "${TRACK_BRANCH}" || true
		git branch --set-upstream-to="${ORG_REMOTE_NAME}/${TRACK_BRANCH}" "${TRACK_BRANCH}" >/dev/null
	else
		yellow "==> Skipping upstream retarget: ${ORG_REMOTE_NAME}/${TRACK_BRANCH} not found"
	fi
fi

# --- 5) Optional: drop legacy/extra remotes ------------------------------
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
    git push                          # → BOTH the org repo and the fork
    git pull                          # ← ${ORG_REMOTE_NAME} (the org repo)
    git push ${FORK_REMOTE_NAME} <ref>$(printf '%*s' $((23 - ${#FORK_REMOTE_NAME})) '')# → the fork only
    make release-to-org TAG=vX.Y.Z    # tag a release and push branch + tag
    make sync-from-org                # ← pull org main into local main

'${TRACK_BRANCH:-main}' tracks ${ORG_REMOTE_NAME}/${TRACK_BRANCH:-main}, so pulls and status read from
the org repo. The protect-upstream-push pre-push gate is deliberately
unwired (see .pre-commit-config.yaml): ordinary pushes of '${TRACK_BRANCH:-main}' are
MEANT to reach the org repo now. Re-add that hook block if you want to go
back to milestone-only releases.
EOF
