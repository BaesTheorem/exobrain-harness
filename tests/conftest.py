"""Shared test helpers.

Most scripts in this repo have hyphenated filenames and are not importable
through the normal mechanism, which is also why they cannot leak into each
other (see checks/check_boundaries.py). Tests load them by file path instead.
Modules are cached so each script's module-level constants build once.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

# Loaded scripts are dynamic modules; Any is honest here, and it keeps
# pyright from flagging every attribute access in the tests.
_cache: dict[str, Any] = {}


def load_script(rel_path: str) -> Any:
    """Import a repo script by path, tolerating hyphens in the filename."""
    if rel_path in _cache:
        return _cache[rel_path]
    path = REPO / rel_path
    name = "script_" + path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _cache[rel_path] = mod
    return mod


def script_exists(rel_path: str) -> bool:
    return (REPO / rel_path).exists()
