#!/usr/bin/env python3
"""Module-boundary checker: each top-level tool directory is an island.

The rule this enforces: a script may import the stdlib, third-party packages,
and modules inside its OWN top-level directory. It may not import another
tool's internals, and it may not sys.path its way into a sibling tool.

Why not import-linter: that tool assumes an importable package graph. This
repo is deliberately a set of independent scripts (many dirs are hyphenated
and unimportable), so the only realistic boundary violations are
  1. `import X` where X is a module that lives in a different island, or
  2. sys.path.insert/append pointing at a sibling island's directory.
Both are detectable from the AST without executing anything.

Blessed cross-island imports (a deliberate public interface) go in
ALLOWED_CROSS below, with a reason. Everything else fails.

Usage:
    check_boundaries.py            # whole repo (CI / pre-commit style)
    check_boundaries.py FILE...    # just these files (post-edit hook style)
Exit 1 on violations, 0 otherwise.
"""

import ast
import re
import subprocess
import sys
import sys as _sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (importer island, imported module) -> reason. Keep this SHORT; every entry
# is a coupling that every future edit to the exporter has to respect.
ALLOWED_CROSS: dict[tuple[str, str], str] = {}

# stdlib_module_names is 3.10+; the fallback covers interpreters like the
# macOS system 3.9 that hooks may run under. The filter matters because repo
# modules can shadow stdlib names (solo-dm ships a calendar.py): without it,
# every legitimate `import calendar` reads as a cross-island reach.
if hasattr(_sys, "stdlib_module_names"):
    STDLIB = set(_sys.stdlib_module_names)
else:
    STDLIB = {
        "abc", "argparse", "ast", "asyncio", "base64", "calendar", "collections",
        "concurrent", "configparser", "contextlib", "copy", "csv", "ctypes",
        "dataclasses", "datetime", "decimal", "difflib", "email", "enum", "errno",
        "fcntl", "fnmatch", "functools", "getpass", "glob", "gzip", "hashlib",
        "heapq", "hmac", "html", "http", "importlib", "inspect", "io", "itertools",
        "json", "logging", "math", "mimetypes", "multiprocessing", "os", "pathlib",
        "pickle", "plistlib", "pprint", "queue", "random", "re", "sched", "secrets",
        "select", "shlex", "shutil", "signal", "site", "smtplib", "socket",
        "sqlite3", "ssl", "stat", "statistics", "string", "struct", "subprocess",
        "sys", "sysconfig", "tempfile", "textwrap", "threading", "time", "tomllib",
        "traceback", "types", "typing", "unicodedata", "unittest", "urllib", "uuid",
        "venv", "warnings", "wave", "weakref", "xml", "zipfile", "zlib",
    }


def tracked_py_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [REPO / line for line in out.splitlines() if line.strip()]


def island_of(path: Path) -> str:
    """Top-level repo dir the file lives in ('' for repo root)."""
    rel = path.resolve().relative_to(REPO)
    return rel.parts[0] if len(rel.parts) > 1 else ""


def build_export_map(files: list[Path]) -> dict[str, set[str]]:
    """importable module name -> set of islands that define it.

    Hyphenated names are skipped: Python cannot import them, so they cannot
    leak across islands in the first place.
    """
    exports: dict[str, set[str]] = {}
    for f in files:
        stem = f.stem
        if "-" in stem or stem == "__init__":
            continue
        exports.setdefault(stem, set()).add(island_of(f))
    return exports


def check_file(path: Path, exports: dict[str, set[str]]) -> list[str]:
    problems = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [f"{path}: syntax error at line {e.lineno} (boundary check skipped the rest)"]

    my_island = island_of(path)
    rel = path.relative_to(REPO)

    for node in ast.walk(tree):
        # 1. Cross-island imports.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            else:
                names = []
            for name in names:
                if name in STDLIB:
                    continue
                owners = exports.get(name, set())
                foreign = owners - {my_island}
                if foreign and my_island not in owners:
                    if (my_island, name) in ALLOWED_CROSS:
                        continue
                    problems.append(
                        f"{rel}:{node.lineno}: imports `{name}`, which belongs to "
                        f"{sorted(foreign)}. Islands do not import each other's internals; "
                        f"shell out to the other tool's CLI, or add an ALLOWED_CROSS entry "
                        f"with a reason in checks/check_boundaries.py."
                    )

        # 2. sys.path pointed at a sibling island.
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if func in ("sys.path.insert", "sys.path.append"):
                arg_src = ast.unparse(node.args[-1]) if node.args else ""
                for other in {i for owners in exports.values() for i in owners}:
                    if not other or other == my_island:
                        continue
                    if re.search(rf"(^|[/'\"]){re.escape(other)}(['\"/]|$)", arg_src):
                        problems.append(
                            f"{rel}:{node.lineno}: sys.path reaches into sibling "
                            f"island `{other}` ({arg_src}). Same rule as above."
                        )
    return problems


def main() -> int:
    all_files = tracked_py_files()
    exports = build_export_map(all_files)
    targets = [Path(a).resolve() for a in sys.argv[1:]] or all_files
    targets = [t for t in targets if t.suffix == ".py" and t.exists()]

    problems = []
    for f in targets:
        try:
            f.resolve().relative_to(REPO)
        except ValueError:
            continue  # outside the repo, not ours to police
        problems.extend(check_file(f, exports))

    if problems:
        print("module boundary violations:")
        for p in problems:
            print("  " + p)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
