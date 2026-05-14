"""End-to-end behavioural tests for scripts/setup-dual-push-remotes.sh.

These tests exist because of a real CI/local incident: the script
originally used `mapfile -t`, which is bash 4+. macOS ships bash 3.2,
so the script aborted with `mapfile: command not found` on the very
first user invocation after PR #9 merged. Syntax-only checks (`bash -n`)
did not catch this — the parser accepts the token; the runtime doesn't.

The tests construct a real git clone with the dual-push misconfig
(origin pushing to two URLs, plus a stray legacy remote), invoke the
script via the SYSTEM bash (not whatever bash happens to be first on
PATH), and assert the post-state matches the documented contract.

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
    """Build three bare repos + a clone with the dual-push misconfig.

    Layout:
      personal-fork.git   stand-in for ArthurKeen/<repo>
      org-repo.git        stand-in for arango-solutions/<repo>
      legacy-remote.git   unrelated remote we want DROP_REMOTES to clean up

    The clone (`work`) starts in the broken state we observed on the
    user's machine: origin's fetch URL points at the personal fork, but
    origin has TWO push URLs (fork + org), AND there's a separately-named
    `arango-solutions` remote that the script is expected to rename.
    """
    personal = tmp_path / "personal-fork.git"
    org = tmp_path / "org-repo.git"
    legacy = tmp_path / "legacy-remote.git"
    for p in (personal, org, legacy):
        p.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(p)], check=True)

    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(personal), str(work)], check=True)

    # Reproduce the dual-push misconfig: origin with TWO explicit push
    # URLs (fork + org). Note: a single `set-url --add --push` REPLACES
    # the implicit pushurl (which equals the fetch URL); to truly get
    # two URLs you have to add both explicitly. This mirrors how the
    # broken state actually arises in the wild — somebody runs `--add
    # --push` twice with different URLs over time, or a tool does it.
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

    env = {**os.environ, **(env_overrides or {})}
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

    result = _run_script(
        workspace["work"],
        {
            "UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git",
        },
    )
    assert result.returncode == 0, (
        f"script failed under system bash:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # If we ever regress to using mapfile / declare -A / ${var^^} / etc,
    # bash 3.2 will surface the failure here. Pin a clear error fragment
    # check too so a passing test guarantees the right fix path was taken.
    assert "command not found" not in result.stdout
    assert "command not found" not in result.stderr


def test_strips_extra_push_url_from_origin(workspace: dict[str, Path]) -> None:
    """The headline misconfig: origin with two push URLs."""
    work = workspace["work"]

    before = _push_urls(work, "origin")
    assert len(before) == 2, f"fixture sanity: origin should start with 2 push URLs, got {before}"

    result = _run_script(work, {"UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git"})
    assert result.returncode == 0, result.stderr

    after = _push_urls(work, "origin")
    assert len(after) == 1, f"origin should have exactly 1 push URL after, got {after}"
    assert after[0] == str(workspace["personal"]), (
        "origin's single push URL must be the personal fork, not the org repo"
    )


def test_renames_arango_solutions_to_upstream(workspace: dict[str, Path]) -> None:
    """A remote named arango-solutions should be renamed to upstream
    (the GitHub fork-workflow convention)."""
    work = workspace["work"]
    result = _run_script(work, {"UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git"})
    assert result.returncode == 0, result.stderr

    remotes = {name for name, _url, _kind in _remotes(work)}
    assert "upstream" in remotes
    assert "arango-solutions" not in remotes


def test_upstream_points_at_org_repo(workspace: dict[str, Path]) -> None:
    """Both fetch and push URLs of `upstream` must equal the org repo URL."""
    work = workspace["work"]
    result = _run_script(work, {"UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git"})
    assert result.returncode == 0, result.stderr

    fetch = _git(["remote", "get-url", "upstream"], work).stdout.strip()
    push_urls = _push_urls(work, "upstream")
    assert fetch == str(workspace["org"])
    assert push_urls == [str(workspace["org"])]


def test_drop_remotes_removes_listed_remotes(workspace: dict[str, Path]) -> None:
    """The DROP_REMOTES env var must remove the listed legacy remotes."""
    work = workspace["work"]
    result = _run_script(
        work,
        {
            "UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git",
            "DROP_REMOTES": "legacy-remote",
        },
    )
    assert result.returncode == 0, result.stderr

    remotes = {name for name, _url, _kind in _remotes(work)}
    assert "legacy-remote" not in remotes


def test_idempotent_when_already_in_target_state(workspace: dict[str, Path]) -> None:
    """Running the script twice must produce the same result (no errors,
    no duplicate URLs)."""
    work = workspace["work"]

    first = _run_script(work, {"UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git"})
    assert first.returncode == 0, first.stderr
    after_first = sorted(_remotes(work))

    second = _run_script(work, {"UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git"})
    assert second.returncode == 0, second.stderr
    after_second = sorted(_remotes(work))

    assert after_first == after_second, (
        "script should be idempotent — running twice changes nothing"
    )


def test_explicit_url_overrides_take_precedence(workspace: dict[str, Path], tmp_path: Path) -> None:
    """Explicit ORIGIN_URL / UPSTREAM_URL env vars must win over the
    discovery heuristics so users can force a specific layout."""
    work = workspace["work"]

    # Build a second pair of URLs the script will discover by env, not
    # by introspection.
    alt_personal = tmp_path / "alt-personal.git"
    alt_org = tmp_path / "alt-org.git"
    for p in (alt_personal, alt_org):
        p.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(p)], check=True)

    result = _run_script(
        work,
        {
            "ORIGIN_URL": str(alt_personal),
            "UPSTREAM_URL": str(alt_org),
            "UPSTREAM_PROTECTED_URL_PATTERN": "alt-org.git",
        },
    )
    assert result.returncode == 0, result.stderr

    origin_fetch = _git(["remote", "get-url", "origin"], work).stdout.strip()
    upstream_fetch = _git(["remote", "get-url", "upstream"], work).stdout.strip()
    assert origin_fetch == str(alt_personal)
    assert upstream_fetch == str(alt_org)


def test_refuses_when_origin_and_upstream_urls_collide(workspace: dict[str, Path]) -> None:
    """If the explicit overrides pick the same URL for both remotes, the
    script must refuse — that misconfig is the very thing we're fixing."""
    work = workspace["work"]
    same_url = str(workspace["org"])
    result = _run_script(
        work,
        {
            "ORIGIN_URL": same_url,
            "UPSTREAM_URL": same_url,
            "UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git",
        },
    )
    assert result.returncode == 1
    assert "must differ" in result.stderr


def test_prints_clean_final_layout(workspace: dict[str, Path]) -> None:
    """Output should include a 'Final remote layout' summary the user
    can sanity-check."""
    work = workspace["work"]
    result = _run_script(
        work,
        {
            "UPSTREAM_PROTECTED_URL_PATTERN": "org-repo.git",
            "DROP_REMOTES": "legacy-remote",
        },
    )
    assert result.returncode == 0
    assert "Final remote layout" in result.stdout
    assert "Setup complete" in result.stdout
    assert "make release-to-org" in result.stdout


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
