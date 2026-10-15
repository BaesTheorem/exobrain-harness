"""traces/trace_archive.py keeps every transcript, even after the source is gone.

Runs the archiver through its own venv (it needs Python 3.14 for
compression.zstd, and pytest runs on an older interpreter).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PY = REPO / "traces" / ".venv" / "bin" / "python"
SCRIPT = REPO / "traces" / "trace_archive.py"

pytestmark = pytest.mark.skipif(not PY.exists(), reason="traces/.venv not built (see traces/README.md)")


def archive(src: Path, dest: Path, runs: Path) -> dict:
    out = subprocess.run([str(PY), str(SCRIPT), "--source", str(src), "--dest", str(dest),
                          "--runs-log", str(runs), "--level", "3"],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def unzstd(path: Path) -> bytes:
    code = "import sys; from compression import zstd; sys.stdout.buffer.write(zstd.ZstdFile(sys.argv[1]).read())"
    return subprocess.run([str(PY), "-c", code, str(path)], capture_output=True, check=True).stdout


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    src = tmp_path / "projects"
    proj = src / "-Users-x-proj"
    (proj / "s1" / "subagents").mkdir(parents=True)
    (proj / "s1" / "tool-results").mkdir()
    (proj / "memory").mkdir()
    (proj / "s1.jsonl").write_text('{"type":"user"}\n')
    (proj / "s1" / "subagents" / "agent-a.jsonl").write_text('{"type":"assistant"}\n')
    (proj / "s1" / "tool-results" / "t.txt").write_bytes(os.urandom(4096))
    (proj / "memory" / "MEMORY.md").write_text("index\n")
    return src, tmp_path / "archive", tmp_path / "runs.jsonl"


def test_archives_every_file_byte_for_byte_but_not_through_symlinks(tree):
    src, dest, runs = tree
    (src / "-Users-y-other").mkdir()
    (src / "-Users-y-other" / "memory").symlink_to(src / "-Users-x-proj" / "memory")
    summary = archive(src, dest, runs)
    assert summary["new"] == 4 and summary["error_count"] == 0
    got = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*.zst"))
    assert got == ["-Users-x-proj/memory/MEMORY.md.zst", "-Users-x-proj/s1.jsonl.zst",
                   "-Users-x-proj/s1/subagents/agent-a.jsonl.zst", "-Users-x-proj/s1/tool-results/t.txt.zst"]
    for rel in got:
        original = src / rel.removesuffix(".zst")
        assert unzstd(dest / rel) == original.read_bytes()
        assert (dest / rel).stat().st_mtime_ns == original.stat().st_mtime_ns


def test_second_run_is_a_no_op_and_an_append_is_rearchived(tree):
    src, dest, runs = tree
    archive(src, dest, runs)
    assert archive(src, dest, runs)["new"] + archive(src, dest, runs)["updated"] == 0
    session = src / "-Users-x-proj" / "s1.jsonl"
    with open(session, "a") as fh:
        fh.write('{"type":"assistant"}\n')
    os.utime(session, ns=(session.stat().st_atime_ns, session.stat().st_mtime_ns + 1_000_000))
    summary = archive(src, dest, runs)
    assert summary["updated"] == 1
    assert unzstd(dest / "-Users-x-proj" / "s1.jsonl.zst") == session.read_bytes()


def test_a_pruned_source_keeps_its_archive_copy(tree):
    src, dest, runs = tree
    archive(src, dest, runs)
    (src / "-Users-x-proj" / "s1.jsonl").unlink()
    summary = archive(src, dest, runs)
    assert summary["rescued"] == 1
    assert unzstd(dest / "-Users-x-proj" / "s1.jsonl.zst") == b'{"type":"user"}\n'
    assert len(runs.read_text().splitlines()) == 2
