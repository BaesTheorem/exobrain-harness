"""Tests for the --history mode of the cybersecurity-bodyguard exposure audit.

The load-bearing test is `test_finds_secret_deleted_from_worktree`: the entire
reason this mode exists is that --staged and --path only see current content,
so a credential committed once and deleted in the next commit passes both while
staying readable forever in the object store. If that test ever goes green for
the wrong reason, the mode is decorative.
"""

import subprocess
from pathlib import Path

from conftest import load_script

audit = load_script(".claude/skills/cybersecurity-bodyguard/scripts/exposure_audit.py")

# Shaped like a real AWS key so SECRET_PATTERNS matches; not a live credential.
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    return repo


def commit(repo: Path, name: str, body: str, msg: str) -> None:
    (repo / name).write_text(body)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def scan(repo: Path) -> list[dict]:
    return audit.scan_history(repo, [], 2_000_000)


def categories(findings: list[dict]) -> list[str]:
    return [f["category"] for f in findings]


def test_finds_secret_deleted_from_worktree(tmp_path):
    """The case --staged and --path structurally cannot see."""
    repo = make_repo(tmp_path)
    commit(repo, "config.py", f'key = "{FAKE_KEY}"\n', "add config")
    commit(repo, "config.py", 'key = os.environ["AWS_KEY"]\n', "move key to env")

    # Control: the worktree really is clean, so a hit below comes from history.
    assert FAKE_KEY not in (repo / "config.py").read_text()
    assert audit.scan_path(repo / "config.py", []) == []

    findings = scan(repo)
    assert categories(findings) == ["secret:aws_access_key"]
    assert findings[0]["file"].startswith("config.py@")


def test_snippet_never_echoes_the_credential(tmp_path):
    """Findings are reported to a terminal and to logs; they must stay redacted."""
    repo = make_repo(tmp_path)
    commit(repo, "config.py", f'key = "{FAKE_KEY}"\n', "add config")

    for finding in scan(repo):
        assert FAKE_KEY not in finding["snippet"]


def test_unchanged_secret_reports_once_not_once_per_commit(tmp_path):
    """Dedup on (category, path, line, snippet) keeps long histories readable."""
    repo = make_repo(tmp_path)
    commit(repo, "config.py", f'key = "{FAKE_KEY}"\n', "add config")
    for i in range(6):
        commit(repo, "notes.txt", f"line {i}\n", f"unrelated {i}")

    assert len(scan(repo)) == 1


def test_scans_refs_that_were_never_merged(tmp_path):
    """A secret abandoned on a side branch is still published with the repo."""
    repo = make_repo(tmp_path)
    commit(repo, "readme.md", "hello\n", "init")
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "token.txt", f"{FAKE_KEY}\n", "side secret")
    git(repo, "checkout", "-q", "-")

    assert categories(scan(repo)) == ["secret:aws_access_key"]


def test_binary_blobs_do_not_break_the_scan(tmp_path):
    """A NUL-heavy blob must be skipped without hiding the text blob beside it."""
    repo = make_repo(tmp_path)
    (repo / "blob.bin").write_bytes(bytes(range(256)) * 64)
    commit(repo, "k.txt", f"{FAKE_KEY}\n", "mixed commit")

    assert categories(scan(repo)) == ["secret:aws_access_key"]


def test_oversized_blobs_are_skipped(tmp_path):
    """max_bytes is a real guard, not decoration."""
    repo = make_repo(tmp_path)
    commit(repo, "big.txt", f"{FAKE_KEY}\n" + "x" * 5000, "big file")

    assert audit.scan_history(repo, [], 1_000) == []   # 5KB blob, 1KB budget
    assert len(scan(repo)) == 1                        # same blob, real budget


def test_clean_history_is_clean(tmp_path):
    """Guards against a scanner that flags everything."""
    repo = make_repo(tmp_path)
    commit(repo, "readme.md", "nothing sensitive here\n", "init")

    assert scan(repo) == []


def test_empty_repo_does_not_raise(tmp_path):
    assert scan(make_repo(tmp_path)) == []
