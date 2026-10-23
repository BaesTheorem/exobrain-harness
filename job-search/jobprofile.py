"""The candidate profile: every personal value the pipeline uses, in one file.

Lanes, gates and tools read the search owner's rules from `profile.yaml`
(gitignored) instead of from code, so one clone serves any candidate. Copy
`profile.example.yaml` to `profile.yaml` and edit it; `doctor.py` checks it.

Lookup order for the file: `$JOB_PIPELINE_PROFILE`, then `profile.yaml` at the
repo root. Two comp keys also accept an override from the environment or the
repo `.env`: `JOB_COMP_FLOOR` and `JOB_ONSITE_FLOOR` (the test suite uses this).

INVARIANTS
- No personal value (floor, city, title, path) is hardcoded in this module.
- A missing or malformed required key raises ProfileError naming the key.
- Title and metro lists are regex fragments joined as alternatives inside
  word boundaries, so a profile entry like "sr\\.?" works as written.
"""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent


class ProfileError(RuntimeError):
    pass


def profile_path() -> Path:
    env = os.environ.get("JOB_PIPELINE_PROFILE")
    return Path(env).expanduser() if env else REPO / "profile.yaml"


@functools.lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    path = profile_path()
    if not path.exists():
        raise ProfileError(
            f"no profile at {path}. Copy profile.example.yaml to profile.yaml and edit it, "
            "or set JOB_PIPELINE_PROFILE.")
    import yaml  # PyYAML; imported late so `--help` works without it

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"{path} must hold a YAML mapping")
    return data


def get(dotted: str, default: Any = ..., data: dict[str, Any] | None = None) -> Any:
    """Read `a.b.c` from the profile. No default means the key is required."""
    node: Any = load() if data is None else data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node or node[part] is None:
            if default is ...:
                raise ProfileError(f"profile key `{dotted}` is not set ({profile_path()})")
            return default
        node = node[part]
    return node


# --- compensation ---------------------------------------------------------

def dotenv(name: str) -> str | None:
    """A value from the repo-root `.env` (gitignored), or None."""
    path = REPO / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.removeprefix("export ").strip() == name and v.strip():
            return v.strip().strip('"').strip("'")
    return None


def _money(key: str, env: str) -> int:
    raw = os.environ.get(env) or dotenv(env)
    if raw is None:
        raw = get(key)
    try:
        return int(str(raw).replace(",", "").replace("_", ""))
    except ValueError as e:
        raise ProfileError(f"`{key}` = {raw!r} is not a whole number of dollars") from e


def comp_floor() -> int:
    """Annual floor for remote seats (gate 3, band rule)."""
    return _money("comp.remote_floor", "JOB_COMP_FLOOR")


def onsite_floor() -> int:
    """Annual floor for any seat with an office requirement inside the home metro."""
    return _money("comp.onsite_floor", "JOB_ONSITE_FLOOR")


# --- regex lists ----------------------------------------------------------

def alternation(items: list[str], bounded: bool = True) -> re.Pattern[str]:
    if not items:
        return re.compile(r"(?!x)x")  # matches nothing
    body = "|".join(f"(?:{i})" for i in items)
    return re.compile(rf"\b(?:{body})\b" if bounded else body, re.I)


@functools.lru_cache(maxsize=None)
def title_re(kind: str) -> re.Pattern[str]:
    """kind: keep | drop | off_lane | strong. Only `keep` is required."""
    items = get(f"titles.{kind}") if kind == "keep" else get(f"titles.{kind}", [])
    return alternation(list(items))


@functools.lru_cache(maxsize=1)
def off_lane_re() -> re.Pattern[str]:
    """Titles that pass `keep` on a generic word ("analyst") but belong to
    another field. Full regexes, not word fragments, so they can say
    "financial ... analyst" with a gap."""
    return alternation(list(get("titles.off_lane", [])), bounded=False)


# --- location -------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def metro_re() -> re.Pattern[str]:
    """Matches a location string inside the home metro. Matches nothing when
    the profile has no metro (remote-only search)."""
    cities = get("location.metro.cities", [])
    return alternation(list(cities), bounded=False)


def has_metro() -> bool:
    return bool(get("location.metro.cities", []))


def metro_name() -> str:
    return get("location.metro.name", "home metro")


def metro_search() -> str:
    """The location string the boards take, for example "Kansas City, MO"."""
    return get("location.metro.search")


def metro_radius() -> int:
    return int(get("location.metro.radius_mi", 30))


def metro_tag() -> str:
    """Short label printed on local rows, for example "KC-LOCAL"."""
    return get("location.metro.tag", "LOCAL")


# --- knockouts ------------------------------------------------------------

def knockout(name: str, default: Any = None) -> Any:
    return get(f"knockouts.{name}", default)


# --- paths ----------------------------------------------------------------

def _path(p: str) -> Path:
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else REPO / q


def listings_dir() -> Path:
    """Where one markdown note per posting lives (an Obsidian folder works)."""
    return _path(get("paths.listings"))


def archive_dirs() -> list[Path]:
    return [_path(p) for p in get("paths.archive", [])]


def search_roots() -> list[Path]:
    """Every folder that can hold a `type: job-listing` note."""
    return [listings_dir(), *archive_dirs()]


def state_dir() -> Path:
    d = _path(get("paths.state", "state"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def capabilities_file() -> Path | None:
    p = get("candidate.capabilities", None)
    return _path(p) if p else None


def walk_roots():
    """os.walk over every search root, so callers can prune `dirs` in place."""
    seen: set[Path] = set()
    for r in search_roots():
        r = r.resolve()
        if r in seen or not r.exists():
            continue
        seen.add(r)
        yield from os.walk(r)


def metro_search_long() -> str:
    """Long form for boards that want the full state name, for example
    "Kansas City, Missouri". Falls back to `metro.search`."""
    return get("location.metro.search_long", None) or metro_search()


def metro_city() -> str:
    return metro_search().split(",")[0].strip()


def with_local(remote_pass: Any, local_pass: Any) -> list[Any]:
    """[remote_pass] plus the home-metro pass when the profile has a metro.
    `local_pass` is a value or a zero-argument callable, so a remote-only
    profile never evaluates the metro keys."""
    if not has_metro():
        return [remote_pass]
    return [remote_pass, local_pass() if callable(local_pass) else local_pass]
