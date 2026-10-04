"""Scripts with an `env python3` shebang must import under Apple Python 3.9.

Under launchd, PATH has no Homebrew, so `env python3` resolves to
/usr/bin/python3 (3.9). A PEP 604 annotation (`str | None`) on a def is then
evaluated at import and raises TypeError, unless the module has
`from __future__ import annotations`. This failure stopped every watcher's
Discord copy from 2026-10-03 to 2026-10-04 (bin/discord-dm).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN_DIRS = [REPO / "bin", REPO / "mist-voice" / "bin"]


def shebang_scripts() -> list[Path]:
    out = []
    for d in BIN_DIRS:
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            try:
                first = f.open("rb").readline()
            except OSError:
                continue
            if first.startswith(b"#!/usr/bin/env python3"):
                out.append(f)
    return out


def uses_union_annotation(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anns = [a.annotation for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs]
            anns.append(node.returns)
            for ann in anns:
                if ann is not None and any(
                    isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(ann)
                ):
                    return True
    return False


def has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )


@pytest.mark.parametrize("script", shebang_scripts(), ids=lambda p: p.name)
def test_union_annotations_have_future_import(script: Path) -> None:
    tree = ast.parse(script.read_text())
    if uses_union_annotation(tree):
        assert has_future_annotations(tree), f"{script.name}: add `from __future__ import annotations`"
