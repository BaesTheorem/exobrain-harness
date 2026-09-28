"""Compensation floors for the job-search lanes, read from config, never from code.

The floors are personal (they encode what Alex will accept), so they live in
the gitignored harness `.env`, not in this public repo. Every lane imports
them from here:

    JOB_COMP_FLOOR     remote / standard-lane floor, annual USD
    JOB_ONSITE_FLOOR   floor for any seat with an office requirement, annual USD

Lookup order: the process environment, then the harness root `.env`. A missing
or non-numeric value raises; there is deliberately no numeric default, so a
fresh clone fails loudly instead of gating on somebody else's number.

INVARIANTS
- No compensation figure appears in this file or in any lane that imports it.
- A missing key raises FloorConfigError naming `.env.example`.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class FloorConfigError(RuntimeError):
    pass


def _from_dotenv(key: str, env_path: Path) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().removeprefix("export ").strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def read_floor(key: str, env_path: Path = ENV_PATH) -> int:
    raw = os.environ.get(key) or _from_dotenv(key, env_path)
    if not raw:
        raise FloorConfigError(
            f"{key} is not set. Add it to the harness .env (see .env.example at the "
            f"repo root), e.g. {key}=<annual USD>, or export it in the environment.")
    try:
        return int(raw.replace(",", "").replace("_", ""))
    except ValueError as e:
        raise FloorConfigError(f"{key}={raw!r} is not a whole number of dollars") from e


def comp_floor() -> int:
    return read_floor("JOB_COMP_FLOOR")


def onsite_floor() -> int:
    return read_floor("JOB_ONSITE_FLOOR")
