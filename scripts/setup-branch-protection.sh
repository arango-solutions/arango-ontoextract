#!/usr/bin/env bash
# Tier C — apply GitHub branch protection on `main` so CI is the real enforcer.
#
# Required: `gh` CLI authenticated as a repo admin.
# Idempotent: the API call is a PUT; rerun to update.
#
# Override the repo / branch via env:
#   REPO=org/repo BRANCH=main scripts/setup-branch-protection.sh
set -euo pipefail

REPO="${REPO:-arango-solutions/arango-ontoextract}"
BRANCH="${BRANCH:-main}"

if ! command -v gh >/dev/null 2>&1; then
	echo "setup-branch-protection: gh CLI not found. Install: https://cli.github.com/" >&2
	exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
	echo "setup-branch-protection: jq not found. Install: https://jqlang.org/download/" >&2
	exit 1
fi

# These names must match the `name:` fields of the jobs in
# .github/workflows/ci.yml. Update both places when CI job names change.
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

echo "==> Applying branch protection on ${REPO}@${BRANCH}"
echo "${payload}" | jq .
echo "${payload}" | gh api -X PUT \
	-H "Accept: application/vnd.github+json" \
	"repos/${REPO}/branches/${BRANCH}/protection" \
	--input -

echo "==> Branch protection applied. Verify in:"
echo "    https://github.com/${REPO}/settings/branches"
