"""A fantasy script that starts a sibling Python CLI must pass sys.executable.

The sibling CLIs start with `#!/usr/bin/env python3`. Under launchd the PATH
is bare, so that shebang resolves to /usr/bin/python3 (3.9), and the CLIs use
3.10+ syntax. A call such as subprocess.run([str(ESPN), ...]) then fails on
every launchd run but passes in a terminal (stream-scan, 2026-09-22 to
2026-11-06).
"""
import re
from pathlib import Path

FANTASY = Path(__file__).resolve().parent.parent / "fantasy"
PY_SIBLINGS = sorted(
    p.name for p in (FANTASY / "bin").iterdir()
    if p.is_file() and p.read_text(errors="ignore").startswith("#!/usr/bin/env python3")
)
# subprocess.run([str(X), ...]) or [str(DIR / "bin" / "x"), ...] with no interpreter first
CALL = re.compile(r"subprocess\.(?:run|check_output|Popen|call)\(\s*\[\s*str\(([^)]*)\)")


def _const_targets(src: str) -> dict[str, str]:
    """NAME = ... "file" assignments, mapped to the file name they point at."""
    out = {}
    for m in re.finditer(r'^([A-Z_]+)\s*=.*["\']([\w-]+)["\']\s*\)?\s*$', src, re.M):
        out[m.group(1)] = m.group(2)
    return out


def test_python_siblings_are_called_with_sys_executable():
    assert "espn" in PY_SIBLINGS  # positive control: the scan sees the CLIs
    bad = []
    for f in [*(FANTASY / "bin").iterdir(), *(FANTASY / "espncli").glob("*.py")]:
        if not f.is_file():
            continue
        src = f.read_text(errors="ignore")
        consts = _const_targets(src)
        for m in CALL.finditer(src):
            arg = m.group(1).strip()
            name = consts.get(arg) or (re.findall(r'["\']([\w-]+)["\']', arg) or [""])[-1]
            if name in PY_SIBLINGS:
                line = src.count("\n", 0, m.start()) + 1
                bad.append(f"{f.relative_to(FANTASY)}:{line} runs {name} via its shebang")
    assert not bad, "pass sys.executable first:\n" + "\n".join(bad)
