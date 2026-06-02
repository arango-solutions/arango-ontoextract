#!/usr/bin/env bash
# protect-upstream-push.sh — pre-push hook that gates pushes to a protected
# upstream remote (typically the org/release repo) so that only tagged
# releases on `main` can land there.
#
# Designed to be invoked by the pre-commit framework as a `stages: [pre-push]`
# local hook. Pre-commit calls this script with NO stdin (it has already
# consumed git's pre-push stdin) and exposes the push context via env vars:
#
#   PRE_COMMIT_REMOTE_NAME    e.g. "upstream"
#   PRE_COMMIT_REMOTE_URL     e.g. "https://github.com/arango-solutions/foo.git"
#   PRE_COMMIT_REMOTE_BRANCH  e.g. "refs/heads/main" or "refs/tags/v1.0.0"
#   PRE_COMMIT_LOCAL_BRANCH   e.g. "refs/heads/main"
#   PRE_COMMIT_TO_REF         the local sha being pushed
#
# Limitation inherited from the pre-commit framework: only the FIRST push
# record from `git push`'s stdin is reflected here. Single-ref pushes
# (the realistic case — `git push upstream main` or `git push upstream feat/x`)
# are fully covered. For `git push --all upstream` only the first ref is
# inspected; rely on `make release-to-org` (which only ever pushes a tag
# and main) and on GitHub-side rules for `--all`/`--mirror` defence.
#
# Configuration (env vars; defaults sized for arango-ontoextract):
#   UPSTREAM_PROTECTED_URL_PATTERN   substring matched against the remote URL
#                                    Default: "arango-solutions/"
#   UPSTREAM_PROTECTED_BRANCH        protected branch on upstream
#                                    Default: "main"
#   UPSTREAM_RELEASE_TAG_PATTERN     ERE matching valid release tags
#                                    Default: "^v[0-9]+\.[0-9]+\.[0-9]+$"
#   ALLOW_UPSTREAM_PUSH              set to "1" to bypass (escape hatch;
#                                    surfaced in the refusal message)
#   UPSTREAM_HEAD_TAGS               test/advanced seam: if SET (even to empty),
#                                    its newline-separated value is used as the
#                                    list of tags pointing at the pushed commit
#                                    instead of shelling out to `git tag
#                                    --points-at`. Lets the hook's unit tests be
#                                    hermetic regardless of whatever tags happen
#                                    to sit at HEAD — notably during a real
#                                    `make release-to-org`, which tags HEAD
#                                    *before* this pre-push gate runs.
#
# Behaviour:
#   • Remote URL doesn't match pattern  → silent allow (your personal fork)
#   • ALLOW_UPSTREAM_PUSH=1             → loud allow (escape hatch)
#   • Pushing a release tag (TAG_REGEX) → allow
#   • Pushing a non-protected branch    → allow (PR-style branches OK)
#   • Pushing protected branch when
#       HEAD has a release tag pointing
#       at it                           → allow (this IS a release)
#   • Anything else                     → refuse with a helpful message
#
# Direct invocation (for testing) is supported:
#   PRE_COMMIT_REMOTE_URL=... PRE_COMMIT_REMOTE_BRANCH=refs/heads/main \
#     PRE_COMMIT_TO_REF=$(git rev-parse HEAD) \
#     scripts/githooks/protect-upstream-push.sh

set -euo pipefail

PATTERN="${UPSTREAM_PROTECTED_URL_PATTERN:-arango-solutions/}"
PROTECTED_BRANCH="${UPSTREAM_PROTECTED_BRANCH:-main}"
TAG_REGEX="${UPSTREAM_RELEASE_TAG_PATTERN:-^v[0-9]+\\.[0-9]+\\.[0-9]+$}"

remote_name="${PRE_COMMIT_REMOTE_NAME:-}"
remote_url="${PRE_COMMIT_REMOTE_URL:-}"
remote_branch="${PRE_COMMIT_REMOTE_BRANCH:-}"
local_sha="${PRE_COMMIT_TO_REF:-}"

# Pre-commit doesn't always populate every var (e.g. when a push has no
# refs). If the URL is empty there's nothing for us to enforce against.
if [[ -z "${remote_url}" ]]; then
	exit 0
fi

# Not pushing to a protected URL — silent allow. The hook is intentionally
# a no-op for everyday pushes to your personal fork.
if ! grep -q -- "${PATTERN}" <<<"${remote_url}"; then
	exit 0
fi

# Escape hatch — print loudly so the user notices when it's used.
if [[ "${ALLOW_UPSTREAM_PUSH:-}" == "1" ]]; then
	cat >&2 <<-EOF
		protect-upstream-push: ALLOW_UPSTREAM_PUSH=1 set; bypassing protection.
		  Remote: ${remote_name:-?} (${remote_url})
		  This bypass is for emergencies only. Strongly prefer:
		    make release-to-org TAG=vX.Y.Z
	EOF
	exit 0
fi

# Branch / tag classification. PRE_COMMIT_REMOTE_BRANCH carries the ref
# being pushed *to* (e.g. "refs/heads/main", "refs/tags/v1.0.0"). It can
# be empty if pre-commit couldn't determine it; in that case we fall back
# to PRE_COMMIT_LOCAL_BRANCH.
target_ref="${remote_branch:-${PRE_COMMIT_LOCAL_BRANCH:-}}"

case "${target_ref}" in
"")
	# Nothing to enforce — no ref info available.
	exit 0
	;;
refs/tags/*)
	tag_name="${target_ref#refs/tags/}"
	if [[ "${tag_name}" =~ ${TAG_REGEX} ]]; then
		exit 0
	fi
	refusal="tag '${tag_name}' does not match release pattern ${TAG_REGEX}"
	;;
"refs/heads/${PROTECTED_BRANCH}")
	# Pushing the protected branch — only allow if HEAD has a release tag
	# pointing at exactly this commit. `git tag --points-at` lists tags
	# whose target is the given sha.
	if [[ -z "${local_sha}" ]]; then
		refusal="cannot determine local sha being pushed (PRE_COMMIT_TO_REF empty)"
	else
		# Source the candidate tag list. ``${VAR+set}`` is non-empty only
		# when UPSTREAM_HEAD_TAGS is *defined* (even if empty), so an
		# explicit empty value means "no tags at HEAD" rather than falling
		# back to git — that distinction is what keeps the tests hermetic.
		if [[ -n "${UPSTREAM_HEAD_TAGS+set}" ]]; then
			head_tags() { printf '%s\n' "${UPSTREAM_HEAD_TAGS}"; }
		else
			head_tags() { git tag --points-at "${local_sha}" 2>/dev/null || true; }
		fi

		matching_tag=""
		while IFS= read -r t; do
			[[ -z "${t}" ]] && continue
			if [[ "${t}" =~ ${TAG_REGEX} ]]; then
				matching_tag="${t}"
				break
			fi
		done < <(head_tags)

		if [[ -n "${matching_tag}" ]]; then
			exit 0
		fi
		refusal="pushing '${PROTECTED_BRANCH}' to a protected remote requires HEAD to be at a release tag matching ${TAG_REGEX} (HEAD ${local_sha:0:8} has none)"
	fi
	;;
refs/heads/*)
	# Non-protected branch — allow (PR-review workflow).
	exit 0
	;;
*)
	refusal="unsupported ref type '${target_ref}' for protected remote"
	;;
esac

cat >&2 <<EOF

protect-upstream-push: refusing push to ${remote_name:-?} (${remote_url})
  • ${refusal}

Pushes to this remote's '${PROTECTED_BRANCH}' branch are reserved for
tagged releases. To cut a release:

    make release-to-org TAG=vX.Y.Z

To push a feature branch for review, push that branch by name (not '${PROTECTED_BRANCH}')
and open a PR on GitHub.

Emergency bypass (avoid for WIP):
    ALLOW_UPSTREAM_PUSH=1 git push ${remote_name:-<remote>} <ref>
EOF
exit 1
