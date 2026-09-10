"""End-to-end behavioural tests for scripts/setup-dual-push-remotes.sh.

These tests exist because of a real CI/local incident: the script
originally used `mapfile -t`, which is bash 4+. macOS ships bash 3.2,
so the script aborted with `mapfile: command not found` on the very
first user invocation after PR #9 merged. Syntax-only checks (`bash -n`)
did not catch this — the parser accepts the token; the runtime doesn't.
That regression guard is `test_runs_under_system_bash_without_bash4_features`
and it must keep running under the SYSTEM bash, not whatever bash is
first on PATH.

CONTRACT CHANGE (2026-09-08): the org repo is now the PRIMARY. The script
used to enforce `origin = personal fork` and strip every extra push URL so
`git push` could only reach the fork, with the org repo gated behind
`make release-to-org`. It now enforces the opposite:

    origin  fetch -> org repo
    origin  push  -> org repo AND personal fork  (two push URLs)
    fork          -> personal fork only

so one `git push` lands on both. These tests assert that layout.

Each test sets up its own throwaway directory of bare repos so they
neither depend on each other nor leave state behind.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/setup-dual-push-remotes.sh"

# Force the system bash so we replay what users see on macOS / Alpine /
# anywhere else that doesn't ship bash 4. /bin/bash is bash 3.2 on macOS;
# on Linux it's whatever the distro ships (usually bash 5+, which is fine
# — these tests must pass under both).
SYSTEM_BASH = "/bin/bash"

# The fixture's org repo is `org-repo.git`; point discovery at it rather
# than the real "arango-solutions/" default.
PATTERN_ENV = {"ORG_URL_PATTERN": "org-repo.git"}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _remotes(cwd: Path) -> list[tuple[str, str, str]]:
    """Return parsed `git remote -v` output as (name, url, kind) tuples."""
    out = _git(["remote", "-v"], cwd).stdout.strip().splitlines()
    parsed: list[tuple[str, str, str]] = []
    for line in out:
        # Format: <name>\t<url> (fetch|push)
        name, rest = line.split("\t", 1)
        url, kind = rest.rsplit(" ", 1)
        parsed.append((name, url, kind))
    return parsed


def _push_urls(cwd: Path, remote: str) -> list[str]:
    out = _git(["remote", "get-url", "--push", "--all", remote], cwd).stdout.strip()
    return [line for line in out.splitlines() if line]


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[dict[str, Path]]:
    """Build three bare repos + a clone in the OLD layout.

    Layout:
      personal-fork.git   stand-in for ArthurKeen/<repo>
      org-repo.git        stand-in for arango-solutions/<repo>
      legacy-remote.git   unrelated remote we want DROP_REMOTES to clean up

    The clone (`work`) starts in the pre-2026-09-08 state: origin points
    at the personal fork (with a stray second push URL), and the org repo
    hangs off a separately-named `arango-solutions` remote. The script has
    to promote the org repo to `origin` and demote the fork to `fork`.
    """
    personal = tmp_path / "personal-fork.git"
    org = tmp_path / "org-repo.git"
    legacy = tmp_path / "legacy-remote.git"
    for p in (personal, org, legacy):
        p.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(p)], check=True)

    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(personal), str(work)], check=True)

    # origin with TWO explicit push URLs. Note: a single `set-url --add
    # --push` REPLACES the implicit pushurl (which equals the fetch URL);
    # to truly get two you have to add both explicitly.
    _git(["remote", "set-url", "--add", "--push", "origin", str(personal)], work)
    _git(["remote", "set-url", "--add", "--push", "origin", str(org)], work)
    # Plus a separately-named arango-solutions remote.
    _git(["remote", "add", "arango-solutions", str(org)], work)
    # Plus a legacy remote we'll ask DROP_REMOTES to clean up.
    _git(["remote", "add", "legacy-remote", str(legacy)], work)

    yield {
        "work": work,
        "personal": personal,
        "org": org,
        "legacy": legacy,
    }


def _run_script(
    cwd: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the script via the SYSTEM bash so we exercise the bash 3.2
    code path on macOS the same way the user does."""
    import os

    env = {**os.environ, **PATTERN_ENV, **(env_overrides or {})}
    return subprocess.run(
        [SYSTEM_BASH, str(SCRIPT)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_runs_under_system_bash_without_bash4_features(workspace: dict[str, Path]) -> None:
    """Regression for the `mapfile: command not found` bug from PR #9.

    Even on a host where /bin/bash is bash 3.2 (macOS), the script must
    complete without hitting bash-4-only constructs.
    """
    if not Path(SYSTEM_BASH).exists():
        pytest.skip(f"system bash at {SYSTEM_BASH} not found")

    result = _run_script(workspace["work"])
    assert result.returncode == 0, (
        f"script failed under system bash:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # If we ever regress to using mapfile / declare -A / ${var^^} / etc,
    # bash 3.2 will surface the failure here.
    assert "command not found" not in result.stdout
    assert "command not found" not in result.stderr


def test_origin_dual_pushes_to_org_then_fork(workspace: dict[str, Path]) -> None:
    """The headline behaviour: one `git push` must reach both repos.

    Order matters for readability of push output (org first), so this
    asserts the exact list rather than a set.
    """
    work = workspace["work"]
    result = _run_script(work)
    assert result.returncode == 0, result.stderr

    assert _push_urls(work, "origin") == [str(workspace["org"]), str(workspace["personal"])], (
        "origin must push to the org repo first, then the personal fork"
    )


def test_origin_fetches_from_the_org_repo(workspace: dict[str, Path]) -> None:
    """Pulls and `git status` must read from the org repo, not the fork."""
    work = workspace["work"]
    result = _run_script(work)
    assert result.returncode == 0, result.stderr

    assert _git(["remote", "get-url", "origin"], work).stdout.strip() == str(workspace["org"])


def test_fork_remote_is_single_homed_to_the_personal_fork(workspace: dict[str, Path]) -> None:
    """`fork` exists as the secondary and never points at the org repo."""
    work = workspace["work"]
    result = _run_script(work)
    assert result.returncode == 0, result.stderr

    assert _git(["remote", "get-url", "fork"], work).stdout.strip() == str(workspace["personal"])
    assert _push_urls(work, "fork") == [str(workspace["personal"])], (
        "fork must not inherit the org push URL when it is renamed out of origin"
    )


def test_absorbs_a_separately_named_org_remote(workspace: dict[str, Path]) -> None:
    """A leftover `arango-solutions` remote is promoted to `origin`."""
    work = workspace["work"]
    result = _run_script(work)
    assert result.returncode == 0, result.stderr

    remotes = {name for name, _url, _kind in _remotes(work)}
    assert "origin" in remotes
    assert "fork" in remotes
    assert "arango-solutions" not in remotes
    assert "upstream" not in remotes, "the old `upstream` name must not come back"


def test_drop_remotes_removes_listed_remotes(workspace: dict[str, Path]) -> None:
    """The DROP_REMOTES env var must remove the listed legacy remotes."""
    work = workspace["work"]
    result = _run_script(work, {"DROP_REMOTES": "legacy-remote"})
    assert result.returncode == 0, result.stderr

    remotes = {name for name, _url, _kind in _remotes(work)}
    assert "legacy-remote" not in remotes


def test_idempotent_when_already_in_target_state(workspace: dict[str, Path]) -> None:
    """Running the script twice must produce the same result — in
    particular it must not keep appending push URLs to origin."""
    work = workspace["work"]

    first = _run_script(work)
    assert first.returncode == 0, first.stderr
    after_first = sorted(_remotes(work))
    push_after_first = _push_urls(work, "origin")

    second = _run_script(work)
    assert second.returncode == 0, second.stderr

    assert sorted(_remotes(work)) == after_first, "script should be idempotent"
    assert _push_urls(work, "origin") == push_after_first, (
        "re-running must not duplicate origin's push URLs"
    )


def test_explicit_url_overrides_take_precedence(workspace: dict[str, Path], tmp_path: Path) -> None:
    """Explicit ORG_URL / FORK_URL env vars must win over discovery."""
    work = workspace["work"]

    alt_personal = tmp_path / "alt-personal.git"
    alt_org = tmp_path / "alt-org.git"
    for p in (alt_personal, alt_org):
        p.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(p)], check=True)

    result = _run_script(
        work,
        {
            "FORK_URL": str(alt_personal),
            "ORG_URL": str(alt_org),
            "ORG_URL_PATTERN": "alt-org.git",
        },
    )
    assert result.returncode == 0, result.stderr

    assert _git(["remote", "get-url", "origin"], work).stdout.strip() == str(alt_org)
    assert _git(["remote", "get-url", "fork"], work).stdout.strip() == str(alt_personal)


def test_legacy_env_var_names_still_work(workspace: dict[str, Path], tmp_path: Path) -> None:
    """ORIGIN_URL / UPSTREAM_URL were the pre-2026-09-08 names.

    They are kept as aliases so an old invocation in someone's shell
    history does not silently configure the wrong thing: UPSTREAM_URL is
    the org repo, ORIGIN_URL is the fork.
    """
    work = workspace["work"]

    alt_personal = tmp_path / "legacy-personal.git"
    alt_org = tmp_path / "legacy-org.git"
    for p in (alt_personal, alt_org):
        p.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(p)], check=True)

    result = _run_script(
        work,
        {
            "ORIGIN_URL": str(alt_personal),
            "UPSTREAM_URL": str(alt_org),
            "ORG_URL_PATTERN": "legacy-org.git",
        },
    )
    assert result.returncode == 0, result.stderr

    assert _git(["remote", "get-url", "origin"], work).stdout.strip() == str(alt_org)
    assert _push_urls(work, "origin") == [str(alt_org), str(alt_personal)]


def test_refuses_when_org_and_fork_urls_collide(workspace: dict[str, Path]) -> None:
    """If the overrides pick the same URL for both, the script must refuse."""
    work = workspace["work"]
    same_url = str(workspace["org"])
    result = _run_script(work, {"ORG_URL": same_url, "FORK_URL": same_url})
    assert result.returncode == 1
    assert "must differ" in result.stderr


def test_prints_clean_final_layout(workspace: dict[str, Path]) -> None:
    """Output should include a summary the user can sanity-check."""
    work = workspace["work"]
    result = _run_script(work, {"DROP_REMOTES": "legacy-remote"})
    assert result.returncode == 0
    assert "Final remote layout" in result.stdout
    assert "Setup complete" in result.stdout
    assert "BOTH the org repo and the fork" in result.stdout


def test_real_script_path_is_executable() -> None:
    """The script must be executable so users can invoke it directly
    (not only via `bash scripts/...`). This catches accidental loss of
    the +x bit on the tracked file."""
    assert SCRIPT.is_file()
    # We don't assert the exact mode (umask varies) but executable bit
    # for the user must be set.
    mode = SCRIPT.stat().st_mode
    assert mode & 0o100, f"{SCRIPT} should be executable; mode={oct(mode)}"


@pytest.fixture(autouse=True)
def _ensure_git_available() -> None:
    """All tests in this module require `git` on PATH."""
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
