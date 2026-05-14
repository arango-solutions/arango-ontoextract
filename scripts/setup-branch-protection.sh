#!/usr/bin/env bash
# setup-branch-protection.sh — apply branch protection on the org/release
# repo's main branch.
#
# Two profiles available via PROFILE env var:
#
#   PROFILE=solo     (default)   minimal floor for solo developers
#                                using the dual-push workflow:
#                                  - allow_force_pushes: false
#                                  - allow_deletions:    false
#                                Direct pushes by repo collaborators allowed
#                                (the protect-upstream-push.sh local hook is
#                                the real gate; CI runs as a backstop).
#                                See docs/git-hygiene.md "Solo-dev workflow".
#
#   PROFILE=team                 PR-required + status-checks profile, suitable
#                                once a second developer joins. Requires:
#                                  - PR with 1 approving review
#                                  - All CI status checks green (incl. strict
#                                    branch-up-to-date)
#                                  - No force pushes / deletions
#                                  - Conversation resolution required
#                                  - Admins included in the rules
#
# Required: `gh` CLI authenticated as a repo admin. Idempotent: the API
# call is a PUT; rerun to update or to switch profiles.
#
# Override the repo / branch via env:
#   REPO=org/repo BRANCH=main PROFILE=team scripts/setup-branch-protection.sh
set -euo pipefail

REPO="${REPO:-arango-solutions/arango-ontoextract}"
BRANCH="${BRANCH:-main}"
PROFILE="${PROFILE:-solo}"

if ! command -v gh >/dev/null 2>&1; then
	echo "setup-branch-protection: gh CLI not found. Install: https://cli.github.com/" >&2
	exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
	echo "setup-branch-protection: jq not found. Install: https://jqlang.org/download/" >&2
	exit 1
fi

# These names must match the `name:` fields of the jobs in
# .github/workflows/ci.yml. Used only by the `team` profile; included here
# so flipping profiles doesn't require editing two scripts.
CHECKS=(
	"Lint Backend"
	"Lint Frontend"
	"Pre-commit hooks"
	"Unit Tests"
	"Frontend unit tests"
	"Integration Tests"
	"Unified Docker image build + smoke"
	"Backend E2E tests"
)

case "${PROFILE}" in
solo)
	# Minimal floor: only block the genuinely catastrophic actions.
	# Direct pushes are allowed; the local pre-push hook
	# (protect-upstream-push.sh) gates pushes of `main` to tagged releases
	# only. CI runs unconditionally as a post-hoc backstop.
	payload="$(
		jq -n '{
			required_status_checks: null,
			enforce_admins: false,
			required_pull_request_reviews: null,
			restrictions: null,
			allow_force_pushes: false,
			allow_deletions: false,
			required_linear_history: false,
			required_conversation_resolution: false
		}'
	)"
	;;
team)
	contexts_json="$(printf '%s\n' "${CHECKS[@]}" | jq -R . | jq -s .)"
	payload="$(
		jq -n \
			--argjson contexts "${contexts_json}" \
			'{
				required_status_checks: {
					strict: true,
					contexts: $contexts
				},
				enforce_admins: true,
				required_pull_request_reviews: {
					dismiss_stale_reviews: true,
					require_code_owner_reviews: false,
					required_approving_review_count: 1
				},
				restrictions: null,
				allow_force_pushes: false,
				allow_deletions: false,
				required_linear_history: false,
				required_conversation_resolution: true
			}'
	)"
	;;
*)
	echo "setup-branch-protection: unknown PROFILE='${PROFILE}'. Use 'solo' or 'team'." >&2
	exit 1
	;;
esac

echo "==> Applying branch protection (PROFILE=${PROFILE}) on ${REPO}@${BRANCH}"
echo "${payload}" | jq .
echo "${payload}" | gh api -X PUT \
	-H "Accept: application/vnd.github+json" \
	"repos/${REPO}/branches/${BRANCH}/protection" \
	--input -

echo "==> Branch protection applied. Verify in:"
echo "    https://github.com/${REPO}/settings/branches"
