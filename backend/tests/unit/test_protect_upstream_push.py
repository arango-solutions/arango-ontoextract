"""Behavioural tests for scripts/githooks/protect-upstream-push.sh.

The hook is the linchpin of the "personal fork = active, org repo =
release-only" workflow (see docs/git-hygiene.md "Solo-dev workflow"). If
this hook lets a WIP commit through to the protected upstream main, the
whole workflow's promise breaks. So we exercise every branch of the case
statement directly via subprocess.

We invoke the script with the env vars that the pre-commit framework
would set (PRE_COMMIT_REMOTE_*) and assert exit codes + key fragments of
the refusal message. We never call git from the script (it does call
`git tag --points-at` for the tagged-release path; we use a real
short-lived tag in this repo for that case).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/githooks/protect-upstream-push.sh"

PROTECTED_URL = "https://github.com/arango-solutions/arango-ontoextract.git"
NON_PROTECTED_URL = "https://github.com/ArthurKeen/arango-ontoextract.git"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Invoke the protect script with a deterministic environment.

    We intentionally start from os.environ so that PATH / git config /
    HOME etc. are inherited (the script shells out to `git tag`), then
    layer the test-specific PRE_COMMIT_* vars on top.
    """
    full_env = {**os.environ, **env}
    # Strip ALLOW_UPSTREAM_PUSH from the inherited env unless the test
    # specifically sets it — otherwise a developer with the bypass
    # exported in their shell would get spurious passes.
    if "ALLOW_UPSTREAM_PUSH" not in env:
        full_env.pop("ALLOW_UPSTREAM_PUSH", None)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=full_env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def head_sha() -> str:
    """The current HEAD sha of the working repo, used to populate
    PRE_COMMIT_TO_REF for the realistic path."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()


@pytest.fixture
def release_tag_at_head(head_sha: str) -> Iterator[str]:
    """Create a temporary release-shaped tag pointing at HEAD; clean up
    after the test runs so we don't pollute the user's tag list.

    Uses a lightweight tag (no -a/-m) deliberately:
      1. Annotated tags require user.email/user.name to be set in git
         config, which CI runners do not have by default — using -a here
         caused PR #9's first CI run to fail with `fatal: empty ident
         name not allowed`.
      2. The protect script uses `git tag --points-at <sha>`, which lists
         BOTH annotated and lightweight tags pointing at the sha. From
         the script's perspective the tag types are interchangeable.
      3. The release flow (`make release-to-org`) still creates annotated
         tags in real use; that path is exercised by users with git
         identity configured, not by this hook unit test.
    """
    tag = "v999.999.999"
    # Defensive cleanup in case a previous failed run left it behind.
    subprocess.run(
        ["git", "tag", "-d", tag],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "tag", tag, head_sha],
        cwd=str(REPO_ROOT),
        check=True,
    )
    try:
        yield tag
    finally:
        subprocess.run(
            ["git", "tag", "-d", tag],
            cwd=str(REPO_ROOT),
            check=True,
        )


def test_silent_allow_when_remote_url_does_not_match_pattern(head_sha: str) -> None:
    """The hook is a no-op for everyday pushes to the personal fork."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "origin",
            "PRE_COMMIT_REMOTE_URL": NON_PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
        }
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_silent_allow_when_remote_url_is_empty() -> None:
    """No URL means no enforcement; this is the cold-start safety case."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "",
            "PRE_COMMIT_REMOTE_URL": "",
        }
    )
    assert result.returncode == 0


def test_refuses_pushing_main_to_protected_url_without_release_tag(head_sha: str) -> None:
    """The headline failure mode the hook exists to prevent.

    ``UPSTREAM_HEAD_TAGS=""`` pins the "no release tag at HEAD" scenario so
    this test is hermetic even when run *during* a real ``make release-to-org``
    (which tags HEAD with the release tag before the pre-push gate runs).
    """
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_HEAD_TAGS": "",
        }
    )
    assert result.returncode == 1
    assert "refusing push" in result.stderr
    assert "release tag" in result.stderr
    assert "make release-to-org" in result.stderr
    assert "ALLOW_UPSTREAM_PUSH=1" in result.stderr


def test_allows_pushing_main_when_head_has_release_tag(
    head_sha: str, release_tag_at_head: str
) -> None:
    """Tagged release on main is the canonical 'allowed' path."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
        }
    )
    assert result.returncode == 0, result.stderr
    assert release_tag_at_head == "v999.999.999"  # fixture sanity


def test_allows_pushing_main_when_injected_head_tags_contain_a_release_tag(head_sha: str) -> None:
    """The release path, pinned hermetically via the UPSTREAM_HEAD_TAGS seam:
    a release-shaped tag among HEAD's tags allows the protected-branch push."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_HEAD_TAGS": "some-feature\nv4.5.6",
        }
    )
    assert result.returncode == 0, result.stderr


def test_allows_pushing_feature_branch_to_protected_url(head_sha: str) -> None:
    """Non-protected branches go through (PR-review workflow)."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/chore/some-branch",
            "PRE_COMMIT_TO_REF": head_sha,
        }
    )
    assert result.returncode == 0, result.stderr


def test_allows_pushing_release_tag_to_protected_url(head_sha: str) -> None:
    """A release-shaped tag is always allowed."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/tags/v1.2.3",
            "PRE_COMMIT_TO_REF": head_sha,
        }
    )
    assert result.returncode == 0, result.stderr


def test_refuses_pushing_non_release_tag_to_protected_url(head_sha: str) -> None:
    """Random tags shouldn't bypass the release contract."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/tags/random-tag",
            "PRE_COMMIT_TO_REF": head_sha,
        }
    )
    assert result.returncode == 1
    assert "tag 'random-tag' does not match" in result.stderr


def test_allow_upstream_push_env_var_bypasses_with_loud_warning(head_sha: str) -> None:
    """Escape hatch must be loud enough that a developer can't miss it."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
            "ALLOW_UPSTREAM_PUSH": "1",
        }
    )
    assert result.returncode == 0
    assert "ALLOW_UPSTREAM_PUSH=1 set" in result.stderr
    assert "bypassing protection" in result.stderr
    assert "make release-to-org" in result.stderr


def test_url_pattern_is_overridable_via_env(head_sha: str) -> None:
    """Portability: a different repo (different org) should be able to
    use this same script by overriding the pattern."""
    custom_url = "https://github.com/some-other-org/repo.git"
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": custom_url,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_PROTECTED_URL_PATTERN": "some-other-org/",
            "UPSTREAM_HEAD_TAGS": "",
        }
    )
    assert result.returncode == 1
    assert "refusing push" in result.stderr


def test_release_tag_pattern_is_overridable_via_env(head_sha: str) -> None:
    """Repos using calver / non-semver releases should be able to
    customize the accepted tag shape."""
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/tags/2026.05.14",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_RELEASE_TAG_PATTERN": r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$",
        }
    )
    assert result.returncode == 0, result.stderr


def test_protected_branch_is_overridable_via_env(head_sha: str) -> None:
    """A repo whose release branch is not 'main' (e.g. 'release') should
    be able to point the protection at its actual release branch."""
    # First: pushing 'release' to the upstream is now the protected case
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/release",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_PROTECTED_BRANCH": "release",
            "UPSTREAM_HEAD_TAGS": "",
        }
    )
    assert result.returncode == 1
    assert "pushing 'release'" in result.stderr

    # And pushing 'main' is now treated as a non-protected branch (allowed)
    result = _run(
        {
            "PRE_COMMIT_REMOTE_NAME": "upstream",
            "PRE_COMMIT_REMOTE_URL": PROTECTED_URL,
            "PRE_COMMIT_REMOTE_BRANCH": "refs/heads/main",
            "PRE_COMMIT_TO_REF": head_sha,
            "UPSTREAM_PROTECTED_BRANCH": "release",
        }
    )
    assert result.returncode == 0, result.stderr
