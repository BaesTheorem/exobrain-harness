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

import pytest

REPO = Path(__file__).resolve().parent.parent

# Synthetic config the suite runs under, so no test ever reads the real
# (gitignored) harness .env. Round numbers on purpose: tests assert against the
# loaded module constants, never against a figure. Set in pytest_configure
# because test modules load their scripts at collection time, before any
# function-scoped fixture runs.
SYNTHETIC_ENV = {
    "JOB_COMP_FLOOR": "50000",
    "JOB_ONSITE_FLOOR": "60000",
}
_session_patch = pytest.MonkeyPatch()


def pytest_configure(config):
    for key, value in SYNTHETIC_ENV.items():
        _session_patch.setenv(key, value)


def pytest_unconfigure(config):
    _session_patch.undo()

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
    # Scripts import siblings in their own dir (job-search/comp_floors.py),
    # which works when run directly because Python puts the script's dir first.
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec.loader.exec_module(mod)
    _cache[rel_path] = mod
    return mod


def script_exists(rel_path: str) -> bool:
    return (REPO / rel_path).exists()
