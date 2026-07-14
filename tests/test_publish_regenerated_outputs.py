"""Regression coverage for the run #9 sync failure (13 Jul 2026):
`git pull --rebase origin main` conflicting on files that are wholesale
regenerated every run (OCR extractions, summary/status JSON, live.json).
See RACE_CONDITION_FIX_NOTES.md for the incident and
scripts/publish_regenerated_outputs.sh for the fix.

These tests run REAL git commands against real (temporary, local) bare
repositories -- this is deliberately not mocked, since the whole point is
to prove the fix survives an actual git conflict scenario, not just that
the script parses.

CROSS-PLATFORM NOTE: scripts/publish_regenerated_outputs.sh is a bash
script. In production it only ever runs inside GitHub Actions'
ubuntu-latest, where bash is guaranteed present -- these tests exist for
local development confidence, including on Windows (this repo's push
workflow runs `pytest` locally before allowing a push -- see
push_to_github.ps1 / RACE_CONDITION_FIX_NOTES.md). A bare Windows PATH does
not include `bash`, even when Git for Windows (which bundles one) is
installed -- only git.exe is normally on PATH. _find_bash() below checks
PATH first, then derives Git for Windows' bundled bash from wherever
git.exe actually is, before giving up. If truly nothing is found, the whole
module skips cleanly rather than failing the push gate over an environment
issue that has nothing to do with whether the code under test is correct.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "publish_regenerated_outputs.sh"


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found

    git_path = shutil.which("git")
    if git_path:
        # Git for Windows layout is <root>/cmd/git.exe (or <root>/bin/git.exe)
        # with bash at <root>/bin/bash.exe and/or <root>/usr/bin/bash.exe.
        git_bin_dir = Path(git_path).resolve().parent
        for candidate in (
            git_bin_dir.parent / "bin" / "bash.exe",
            git_bin_dir.parent / "usr" / "bin" / "bash.exe",
            git_bin_dir / "bash.exe",
        ):
            if candidate.exists():
                return str(candidate)

    for hardcoded in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if Path(hardcoded).exists():
            return hardcoded

    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(
    BASH is None,
    reason=(
        "No bash interpreter found (checked PATH and common Git for Windows "
        "install locations). These tests only exercise "
        "scripts/publish_regenerated_outputs.sh (a bash script) for local "
        "development confidence -- production always runs it inside GitHub "
        "Actions' ubuntu-latest, which always has bash, so this skip does "
        "not indicate anything is broken. Install Git for Windows or WSL "
        "to run these locally."
    ),
)


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd)


@pytest.fixture()
def origin_and_seed(tmp_path: Path):
    """A bare 'origin' remote plus one seeded clone, mirroring the shape of
    the real repo's regenerated-output paths."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")

    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", str(seed))
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.com")
    (seed / "data/elections/banissa-2025/ocr/extractions").mkdir(parents=True)
    (seed / "data/public/elections").mkdir(parents=True)
    (seed / "data/public/live.json").write_text('{"seq":1}')
    (seed / "data/elections/banissa-2025/ocr/summary.json").write_text('{"docs":0}')
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "branch", "-M", "main")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")
    return tmp_path, origin


def new_clone(tmp_path: Path, origin: Path, name: str) -> Path:
    target = tmp_path / name
    git(tmp_path, "clone", "-q", str(origin), str(target))
    git(target, "checkout", "-q", "main")
    return target


def publish(clone_dir: Path, *paths: str, github_output: Path | None = None) -> subprocess.CompletedProcess:
    env = None
    if github_output is not None:
        # Extend the real environment rather than replace it -- a from-scratch
        # env dict (as this used to build, with a hardcoded Unix PATH) breaks
        # process creation on Windows, which needs several system variables
        # (SystemRoot etc.) just to load bash.exe/git.exe at all.
        env = os.environ.copy()
        env["GITHUB_OUTPUT"] = str(github_output)
    return run([BASH, str(SCRIPT), *paths], cwd=clone_dir, env=env)


PATHS = ("data/elections", "data/public/elections", "data/public/live.json", "data/public/workers")


def test_two_runs_independently_regenerating_the_same_files_never_conflict(origin_and_seed):
    """The exact run #9 failure: two independently-checked-out runs both
    regenerate the same paths (same page_id, different content -- realistic
    since both scanned the same portal). The first publishes; the second,
    still based on the old checkout, must NOT see a merge/rebase conflict.
    """
    tmp_path, origin = origin_and_seed
    run_a = new_clone(tmp_path, origin, "run_a")
    run_b = new_clone(tmp_path, origin, "run_b")

    for clone, tag in ((run_a, "run_a"), (run_b, "run_b")):
        (clone / "data/public/live.json").write_text(f'{{"seq":2,"note":"{tag}"}}')
        (clone / "data/elections/banissa-2025/ocr/summary.json").write_text(f'{{"docs":5,"note":"{tag}"}}')

    result_a = publish(run_a, *PATHS)
    assert result_a.returncode == 0, result_a.stderr
    assert "conflict" not in (result_a.stdout + result_a.stderr).lower()

    result_b = publish(run_b, *PATHS)
    assert result_b.returncode == 0, result_b.stderr
    assert "conflict" not in (result_b.stdout + result_b.stderr).lower()

    verify = new_clone(tmp_path, origin, "verify")
    # Last publish (run_b) should be what's live -- no conflict markers anywhere.
    live = (verify / "data/public/live.json").read_text()
    assert "<<<<<<<" not in live and "=======" not in live and ">>>>>>>" not in live
    assert '"note":"run_b"' in live


def test_unrelated_concurrent_push_is_preserved_not_clobbered(origin_and_seed):
    """A manual push (e.g. PUSH_TO_GITHUB.cmd) landing on main in between
    must survive -- the fix must never silently discard changes outside the
    paths it was asked to publish."""
    tmp_path, origin = origin_and_seed
    run_c = new_clone(tmp_path, origin, "run_c")

    hand_edit = new_clone(tmp_path, origin, "hand_edit")
    (hand_edit / "docs").mkdir()
    (hand_edit / "docs/MANUAL_NOTE.md").write_text("manual note")
    git(hand_edit, "add", "docs/MANUAL_NOTE.md")
    git(hand_edit, "-c", "user.name=sir", "-c", "user.email=sir@example.com", "commit", "-q", "-m", "manual edit")
    push_result = git(hand_edit, "push", "-q", "origin", "main")
    assert push_result.returncode == 0, push_result.stderr

    (run_c / "data/public/live.json").write_text('{"seq":3}')
    result_c = publish(run_c, *PATHS)
    assert result_c.returncode == 0, result_c.stderr

    verify = new_clone(tmp_path, origin, "verify")
    assert (verify / "docs/MANUAL_NOTE.md").exists()
    assert '"seq":3' in (verify / "data/public/live.json").read_text()


def test_no_changes_exits_cleanly_with_changed_false(origin_and_seed):
    tmp_path, origin = origin_and_seed
    run_d = new_clone(tmp_path, origin, "run_d")
    output_file = tmp_path / "gh_output.txt"
    output_file.write_text("")

    result = publish(run_d, *PATHS, github_output=output_file)
    assert result.returncode == 0, result.stderr
    assert "changed=false" in output_file.read_text()


def test_real_change_exits_cleanly_with_changed_true(origin_and_seed):
    tmp_path, origin = origin_and_seed
    run_e = new_clone(tmp_path, origin, "run_e")
    output_file = tmp_path / "gh_output2.txt"
    output_file.write_text("")

    (run_e / "data/public/live.json").write_text('{"seq":4}')
    result = publish(run_e, *PATHS, github_output=output_file)
    assert result.returncode == 0, result.stderr
    assert "changed=true" in output_file.read_text()


def test_missing_paths_do_not_crash_the_script(origin_and_seed):
    """A path that doesn't exist on disk at all (e.g. data/public/workers/
    never created yet) must be skipped, not fail the whole publish -- this
    is the bug this test suite's own development caught: git add fails hard
    on a pathspec with zero matches."""
    tmp_path, origin = origin_and_seed
    run_f = new_clone(tmp_path, origin, "run_f")
    result = publish(run_f, "data/elections", "data/public/elections",
                      "data/public/live.json", "data/this/path/does/not/exist")
    assert result.returncode == 0, result.stderr
